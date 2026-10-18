"""Per-image processing: idempotency check → read → QC → detect → decide → result.json → webhook."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime

from condorin.config import Settings
from condorin.core.decision import decide, presence_score
from condorin.core.detector import Detector
from condorin.core.meta import box_to_webhook, idempotency_key, resolve_image_meta, result_key
from condorin.core.model_card import ModelCard
from condorin.core.qc import run_qc
from condorin.io import storage
from condorin.io.overlay import render_overlay
from condorin.notifier.payload import build_webhook_payload
from condorin.service.schemas import (
    DetectJob,
    Result,
    ResultDetection,
    ResultImage,
    ResultModel,
    ResultQC,
    WebhookStatus,
)
from condorin.service.tasks import WebhookEnqueuer

log = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """The request is about to exceed REQUEST_BUDGET_S; abort cleanly so the task is retried."""


def canonical_uri(uri: str) -> str:
    p = storage.parse_uri(uri)
    return f"gs://{p.bucket}/{p.obj}" if p.scheme == "gs" else str(p.path)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        card: ModelCard,
        detector: Detector,
        webhook: WebhookEnqueuer,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self.card = card
        self.detector = detector
        self.webhook = webhook
        self.rand = rand

    # --- naming -----------------------------------------------------------------------------------

    def result_uri(self, key: str) -> str:
        return storage.join(self.settings.results_uri_prefix, self.card.version, f"{key}.json")

    def overlay_uri(self, key: str) -> str:
        return storage.join(self.settings.overlay_uri_prefix, self.card.version, f"{key}.jpg")

    def key_for(self, uri: str, generation: str) -> str:
        return result_key(uri, generation, self.card.version)

    @property
    def min_confidence(self) -> float:
        s = self.settings.webhook_min_confidence
        return self.card.thresholds.review_low if s is None else s

    # --- processing -------------------------------------------------------------------------------

    def process(self, job: DetectJob) -> tuple[dict, bool]:
        """Returns (result, computed). Raises storage.Transient / BudgetExceeded for retry and
        storage.PermanentError when the image cannot even be identified."""
        t0 = time.monotonic()
        deadline = t0 + self.settings.request_budget_s
        uri = canonical_uri(job.image_uri)
        p = storage.parse_uri(uri)
        info = None
        generation = job.generation
        if generation is None:
            info = storage.stat(uri)  # NotFound here → 4xx: nothing to record
            generation = info.generation
        key = self.key_for(uri, generation)
        idem = idempotency_key(p.bucket, p.obj, generation)
        res_uri = self.result_uri(key)
        ctx = {"job_id": job.job_id, "batch_id": job.batch_id, "image_uri": uri,
               "idempotency_key": idem, "model_version": self.card.version}  # fmt: skip

        if storage.exists(res_uri):
            result = storage.read_json(res_uri)
            self._ensure_webhook(result)
            log.info("result exists, skipped compute", extra=ctx)
            return result, False

        result = Result(
            job_id=job.job_id,
            batch_id=job.batch_id,
            created_at=now_iso(),
            idempotency_key=idem,
            result_key=key,
            image_uri=uri,
            image=ResultImage(bucket=p.bucket, object=p.obj, generation=generation),
            model=ResultModel(
                name=self.card.name,
                version=self.card.version,
                thresholds=self.card.thresholds.model_dump(),
            ),  # fmt: skip
            status="ok",
            positive_class=self.card.positive_class,
        )
        timings: dict[str, int] = {}
        try:
            if info is None:
                info = storage.stat(uri)
            raw = storage.read_bytes(uri, generation)
        except storage.PermanentError as err:
            # The pinned generation is gone (or forbidden): record a failure, do not retry forever.
            result.status = "failed"
            result.error = f"{type(err).__name__}: {err}"
            result.webhook = WebhookStatus(sent=False, reason="failed")
            result.timings_ms = {"total": _ms(t0)}
            data = result.dump()
            storage.write_json(res_uri, data)
            log.error("image unavailable, recorded as failed", extra={**ctx, "error": result.error})
            return data, True
        timings["download"] = _ms(t0)

        # local dev files: parse "<parent dir>/<file>" like "<river>/<file>" in a bucket
        meta_obj = f"{p.path.parent.name}/{p.path.name}" if p.path else p.obj
        meta = resolve_image_meta(p.bucket, meta_obj, info.metadata, job.options.meta_overrides())
        result.image = result.image.model_copy(update=meta)

        t1 = time.monotonic()
        qc = run_qc(raw, self.card.qc, gsd_m=job.options.gsd_m)
        timings["qc"] = _ms(t1)
        result.image.width, result.image.height = qc.width or None, qc.height or None
        result.qc = ResultQC.model_validate(qc.to_dict())
        if not qc.passed:
            result.status = "rejected_qc"
            result.webhook = WebhookStatus(sent=False, reason="rejected_qc")
            timings["total"] = _ms(t0)
            result.timings_ms = timings
            data = result.dump()
            storage.write_json(res_uri, data)
            log.info("rejected by QC", extra={**ctx, "status": "rejected_qc",
                                               "fields": {"reasons": result.qc.reasons}})  # fmt: skip
            return data, True

        self._check_budget(deadline)
        t2 = time.monotonic()
        detections = self.detector.detect(qc.image_bgr)
        timings["inference"] = _ms(t2)
        self._check_budget(deadline)

        score = presence_score(detections, self.card.positive_class)
        decision = decide(score, self.card.thresholds)
        result.score = round(score, 4)
        result.decision = decision
        result.audit_sample = decision == "clear" and self.rand() < self.settings.audit_rate
        bounds = result.image.bounds
        out = []
        for d in sorted(detections, key=lambda d: -d.conf):
            _, lat, lon = box_to_webhook(d.box, qc.width, qc.height, bounds)
            out.append(ResultDetection(cls=d.cls, confidence=round(d.conf, 4),
                                       bbox_xyxy=[round(v, 1) for v in d.box], lat=lat, lon=lon))  # fmt: skip
        result.detections = out
        if bounds is None and any(d.cls == self.card.positive_class for d in detections):
            log.warning("no image bounds: lat/lon will be null in the webhook", extra=ctx)

        if job.options.return_overlay and decision != "clear":
            ov_uri = self.overlay_uri(key)
            storage.write_bytes(ov_uri, render_overlay(qc.image_bgr, detections,
                                                       self.card.positive_class), "image/jpeg")  # fmt: skip
            result.artifacts = {"overlay": ov_uri}

        data = result.dump()
        payload = build_webhook_payload(data, self.min_confidence, self.settings.send_empty)
        event = self._event(data, payload, res_uri) if payload else None
        result.webhook = WebhookStatus(
            sent=payload is not None,
            reason=None if payload else "no_detections",
            task=self.webhook.task_name_for(event) if event else None,
        )
        timings["total"] = _ms(t0)
        result.timings_ms = timings
        data = result.dump()
        storage.write_json(res_uri, data)  # store first, deliver second
        if event:
            self.webhook.enqueue(event)
        log.info("processed", extra={**ctx, "status": "ok", "decision": decision,
                                     "score": result.score, "timings_ms": timings})  # fmt: skip
        return data, True

    # --- helpers ----------------------------------------------------------------------------------

    def _event(self, result: dict, payload: dict, res_uri: str) -> dict:
        return {
            "idempotency_key": result["idempotency_key"],
            "payload": payload,
            "model_version": result["model"]["version"],
            "result_uri": res_uri,
        }

    def _ensure_webhook(self, result: dict) -> None:
        """A retry after a crash between 'write result' and 'enqueue' must still deliver."""
        if not result.get("webhook", {}).get("sent"):
            return
        payload = build_webhook_payload(result, self.min_confidence, self.settings.send_empty)
        if payload:
            res_uri = self.result_uri(result["result_key"])
            self.webhook.enqueue(self._event(result, payload, res_uri))

    def _check_budget(self, deadline: float) -> None:
        if time.monotonic() > deadline:
            raise BudgetExceeded(f"request budget of {self.settings.request_budget_s}s exceeded")


def _ms(t: float) -> int:
    return round((time.monotonic() - t) * 1000)
