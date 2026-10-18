"""POST of one scene to the backend (`POST /api/v1/detections`), with a Google ID token.

The backend deduplicates by Idempotency-Key (`<bucket>/<object>#<generation>`): a resend answers 200
and sends no new alerts, so retrying here and re-running a whole prefix are both safe.
Tokens and secrets are never logged.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

import requests

from condorin.job.config import JobSettings

log = logging.getLogger(__name__)

RETRY_STATUSES = {408, 429}
TOKEN_TTL_S = 45 * 60  # Google ID tokens last 1 h; refresh well before


class DeliveryError(Exception):
    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


def google_id_token(audience: str) -> str:
    """ID token of the runtime service account (metadata server on Cloud Run, ADC locally)."""
    import google.auth.transport.requests
    from google.oauth2 import id_token

    return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)


class Reporter:
    def __init__(
        self,
        settings: JobSettings,
        session: requests.Session | None = None,
        token_fetcher: Callable[[str], str] = google_id_token,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.token_fetcher = token_fetcher
        self.sleep = sleep
        self._token: str | None = None
        self._token_at = 0.0

    def _bearer(self) -> str:
        secret = self.settings.detections_shared_secret
        if secret is not None and secret.get_secret_value():
            return secret.get_secret_value()
        if self._token is None or time.monotonic() - self._token_at > TOKEN_TTL_S:
            self._token = self.token_fetcher(self.settings.audience)
            self._token_at = time.monotonic()
        return self._token

    def post(self, payload: dict, idempotency_key: str) -> dict:
        """Returns the backend's JSON answer (201 new, 200 duplicate). Raises DeliveryError."""
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if self.settings.webhook_mode == "log":
            log.info("webhook (log mode, not sent)", extra={"idempotency_key": idempotency_key,
                                                            "fields": {"payload": payload}})  # fmt: skip
            return {"duplicate": False, "logged": True}

        attempts = self.settings.webhook_attempts
        for attempt in range(1, attempts + 1):
            headers = {
                "Authorization": f"Bearer {self._bearer()}",
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/json",
            }
            try:
                resp = self.session.post(
                    self.settings.webhook_url, data=body, headers=headers,
                    timeout=self.settings.webhook_timeout_s,
                )  # fmt: skip
            except requests.RequestException as err:
                error: DeliveryError = DeliveryError(f"transport error: {type(err).__name__}")
            else:
                if 200 <= resp.status_code < 300:
                    return _json(resp)
                error = DeliveryError(
                    f"backend answered {resp.status_code}", resp.status_code, _json(resp)
                )
                if resp.status_code == 401 and self._token is not None and attempt == 1:
                    self._token = None  # maybe expired: mint a new one once
                elif resp.status_code < 500 and resp.status_code not in RETRY_STATUSES:
                    raise error  # validation or auth problem: retrying will not help
            if attempt < attempts:
                self.sleep(self.settings.webhook_backoff_s * 2 ** (attempt - 1))
        raise error


def _json(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}
    return data if isinstance(data, dict) else {"raw": data}
