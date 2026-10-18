"""Detector service (FastAPI): /detect, /batches, /healthz, /readyz.

HTTP semantics for Cloud Tasks: 2xx = done (a QC rejection or a recorded failure is a successful
outcome), 5xx = retry. Cloud Tasks also retries 4xx responses, so 4xx is only used for requests that
cannot be identified at all (malformed body, unknown image without a pinned generation).
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from condorin import __version__
from condorin.config import Settings, get_settings
from condorin.core.detector import Detector, build_detector
from condorin.core.model_card import MODEL_CARD_FILE, ModelCard, load_model_card
from condorin.io import storage
from condorin.logs import setup_logging
from condorin.service.batches import BatchService, BatchTooLarge
from condorin.service.pipeline import BudgetExceeded, Pipeline
from condorin.service.schemas import BatchRequest, DetectJob, parse_detect_body
from condorin.service.tasks import CloudTasks, WebhookEnqueuer, cloud_tasks_detect_enqueue

log = logging.getLogger(__name__)

BATCH_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def load_card(settings: Settings) -> ModelCard:
    if (Path(settings.model_dir) / MODEL_CARD_FILE).is_file():
        return load_model_card(settings.model_dir)
    if settings.fake_model:
        log.warning("no model card found; using the placeholder card (FAKE_MODEL=1)")
        return ModelCard.placeholder()
    raise FileNotFoundError(f"{MODEL_CARD_FILE} not found in MODEL_DIR={settings.model_dir}")


def create_app(
    settings: Settings | None = None,
    detector: Detector | None = None,
    webhook: WebhookEnqueuer | None = None,
    tasks: CloudTasks | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        setup_logging(s.log_level)
        t0 = time.monotonic()
        card = detector.card if detector is not None else load_card(s)
        det = detector or build_detector(s, card)
        t = card.inference.tile
        det.detect(np.zeros((t, t, 3), np.uint8))  # warm-up
        if hasattr(det, "calls"):
            det.calls = 0
        log.info("model loaded", extra={"model_version": card.version,
                 "fields": {"model_name": card.name, "device": det.device, "fake": s.fake_model,
                            "load_ms": round((time.monotonic() - t0) * 1000)}})  # fmt: skip
        wh = webhook or WebhookEnqueuer(s, tasks)
        pipeline = Pipeline(s, card, det, wh)
        app.state.settings = s
        app.state.pipeline = pipeline
        app.state.tasks = tasks
        yield

    app = FastAPI(title="condorin-detector", version=__version__, lifespan=lifespan)

    def _pipeline() -> Pipeline | None:
        return getattr(app.state, "pipeline", None)

    @app.get("/")
    def root():
        p = _pipeline()
        return {
            "service": "condorin-detector",
            "version": __version__,
            "model": {"name": p.card.name, "version": p.card.version} if p else None,
            "license": "AGPL-3.0-only",
            "source": app.state.settings.source_url,
        }

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        p = _pipeline()
        if p is None:
            return JSONResponse({"ready": False}, status_code=503)
        return {"ready": True, "model_version": p.card.version, "device": p.detector.device}

    @app.post("/detect")
    async def detect(request: Request):
        pipeline = _pipeline()
        try:
            job = parse_detect_body(await request.json())
        except (ValueError, ValidationError) as err:  # JSONDecodeError is a ValueError
            log.error("invalid /detect body", extra={"error": str(err)[:500]})
            return JSONResponse({"error": "invalid body", "detail": str(err)[:500]}, 400)
        return await run_in_threadpool(_run_job, pipeline, job)

    def _run_job(pipeline: Pipeline, job: DetectJob) -> JSONResponse:
        ctx = {"job_id": job.job_id, "batch_id": job.batch_id, "image_uri": job.image_uri}
        try:
            result, computed = pipeline.process(job)
        except storage.PermanentError as err:
            log.error("image not processable", extra={**ctx, "error": str(err)})
            return JSONResponse({"error": type(err).__name__, "detail": str(err)}, 404)
        except (storage.Transient, BudgetExceeded) as err:
            log.warning("transient failure, will be retried", extra={**ctx, "error": repr(err)})
            return JSONResponse({"error": type(err).__name__, "detail": str(err)}, 503)
        except Exception as err:  # noqa: BLE001 - unexpected: let Cloud Tasks retry
            log.exception("unexpected error", extra={**ctx, "error": repr(err)})
            return JSONResponse({"error": "internal"}, 500)
        return JSONResponse({**result, "cached": not computed,
                             "result_uri": pipeline.result_uri(result["result_key"])})  # fmt: skip

    def _batch_service(background: BackgroundTasks | None) -> BatchService:
        pipeline = _pipeline()
        s: Settings = app.state.settings
        if s.detect_mode == "tasks":
            if app.state.tasks is None:
                app.state.tasks = CloudTasks(s)
            enqueue = cloud_tasks_detect_enqueue(s, app.state.tasks)
        else:  # direct: process in this process after the response (dev only)

            def enqueue(job: dict, name: str) -> bool:
                if background is not None:
                    background.add_task(_run_job, pipeline, DetectJob.model_validate(job))
                return True

        return BatchService(pipeline, enqueue)

    @app.post("/batches", status_code=202)
    async def submit_batch(request: Request, background: BackgroundTasks):
        try:
            req = BatchRequest.model_validate(await request.json())
        except (ValueError, ValidationError) as err:
            return JSONResponse({"error": "invalid body", "detail": str(err)[:1000]}, 422)
        service = _batch_service(background)
        try:
            out = await run_in_threadpool(service.submit, req)
        except BatchTooLarge as err:
            return JSONResponse({"error": "invalid batch", "detail": str(err)}, 422)
        except storage.PermanentError as err:
            return JSONResponse({"error": type(err).__name__, "detail": str(err)}, 422)
        except storage.Transient as err:
            return JSONResponse({"error": "transient", "detail": str(err)}, 503)
        return JSONResponse(out, 202)

    @app.get("/batches/{batch_id}")
    async def batch_summary(batch_id: str):
        if not BATCH_ID_RE.fullmatch(batch_id):
            return JSONResponse({"error": "invalid batch_id"}, 400)
        try:
            return await run_in_threadpool(BatchService(_pipeline(), None).summary, batch_id)
        except storage.NotFound:
            return JSONResponse({"error": "batch not found"}, 404)
        except storage.PermanentError as err:
            return JSONResponse({"error": type(err).__name__, "detail": str(err)}, 400)

    return app


app = create_app()
