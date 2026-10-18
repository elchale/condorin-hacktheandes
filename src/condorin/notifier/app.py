"""Notifier service: POST /deliver (from the `webhook` Cloud Tasks queue) → Django webhook."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from condorin import __version__
from condorin.config import Settings, get_settings
from condorin.logs import setup_logging
from condorin.notifier.delivery import USER_AGENT, deliver
from condorin.service.schemas import WebhookEvent

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, client: httpx.Client | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        setup_logging(s.log_level)
        app.state.settings = s
        app.state.client = client or httpx.Client(headers={"User-Agent": USER_AGENT})
        if not s.webhook_url or s.webhook_token is None:
            log.error("WEBHOOK_URL or WEBHOOK_TOKEN is not configured; deliveries will be retried")
        yield
        if client is None:
            app.state.client.close()

    app = FastAPI(title="condorin-notifier", version=__version__, lifespan=lifespan)

    @app.get("/")
    def root():
        return {"service": "condorin-notifier", "version": __version__,
                "source": app.state.settings.source_url, "license": "AGPL-3.0-only"}  # fmt: skip

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        s = app.state.settings
        ready = bool(s.webhook_url) and s.webhook_token is not None
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    @app.post("/deliver")
    async def deliver_endpoint(request: Request):
        s: Settings = app.state.settings
        try:
            body = await request.json()
            event = WebhookEvent.model_validate(body["event"]).model_dump(mode="json")
        except (ValueError, KeyError, TypeError, ValidationError) as err:
            log.error("invalid /deliver body", extra={"error": str(err)[:500]})
            return JSONResponse({"error": "invalid body"}, status_code=400)
        if not s.webhook_url or s.webhook_token is None:
            log.error("webhook not configured, retrying later",
                      extra={"idempotency_key": event["idempotency_key"]})  # fmt: skip
            return JSONResponse({"result": "not_configured"}, status_code=503)
        outcome = await run_in_threadpool(
            deliver,
            event,
            url=s.webhook_url,
            token=s.webhook_token.get_secret_value(),
            client=app.state.client,
            failed_prefix=s.failed_deliveries_uri_prefix,
            timeout=s.webhook_timeout_s,
        )
        return JSONResponse(
            {"result": outcome.result, "django_status": outcome.django_status},
            status_code=outcome.http_status,
        )

    return app


app = create_app()
