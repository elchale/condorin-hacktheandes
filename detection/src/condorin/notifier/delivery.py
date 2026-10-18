"""Webhook delivery to Django with Cloud-Tasks-friendly outcomes.

Return 200 = done (delivered, or permanently failed and dead-lettered to GCS); 503 = retry later.
The bearer token is never logged.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from condorin.io import storage
from condorin.notifier.payload import serialize

log = logging.getLogger(__name__)

USER_AGENT = "condorin-notifier/1"
RETRY_STATUSES = {408, 429}
AUTH_STATUSES = {401, 403}


@dataclass
class DeliveryOutcome:
    http_status: int  # what /deliver returns to Cloud Tasks
    result: str  # delivered | retry | auth_rejected | permanent_failure
    django_status: int | None = None
    detail: str | None = None


def failed_delivery_uri(prefix: str, idempotency_key: str) -> str:
    return storage.join(prefix, f"{hashlib.sha1(idempotency_key.encode()).hexdigest()}.json")


def deliver(
    event: dict,
    *,
    url: str,
    token: str,
    client: httpx.Client,
    failed_prefix: str | None,
    timeout: float = 10.0,
) -> DeliveryOutcome:
    key = event["idempotency_key"]
    body = serialize(event["payload"])
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key,
        "Content-Type": "application/json",
    }
    ctx = {"idempotency_key": key, "model_version": event.get("model_version")}
    try:
        resp = client.post(url, content=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as err:  # timeouts and network errors
        log.warning("webhook transport error, will retry", extra={**ctx, "error": repr(err)})
        return DeliveryOutcome(503, "retry", None, type(err).__name__)

    code = resp.status_code
    ctx["http_status"] = code
    if 200 <= code < 300:
        log.info("webhook delivered", extra=ctx)
        return DeliveryOutcome(200, "delivered", code)
    if code in AUTH_STATUSES:
        # Almost always a rotated or missing token: retry so no event is lost once it is fixed.
        log.error("webhook auth rejected", extra=ctx)
        return DeliveryOutcome(503, "auth_rejected", code)
    if code >= 500 or code in RETRY_STATUSES:
        log.warning("webhook retryable status, will retry", extra=ctx)
        return DeliveryOutcome(503, "retry", code)

    # Any other 4xx is permanent (409 is ambiguous: maybe "duplicate"; treated as failure for now).
    snippet = resp.text[:2000]
    record = {
        "failed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "idempotency_key": key,
        "url": url,
        "status": code,
        "response_snippet": snippet,
        "event": event,
    }
    note = (
        " (409: possibly a duplicate; confirm semantics with the Django team)"
        if code == 409
        else ""
    )
    if failed_prefix:
        uri = failed_delivery_uri(failed_prefix, key)
        try:
            storage.write_json(uri, record)
        except storage.StorageError as err:
            log.error(
                "could not dead-letter delivery, will retry", extra={**ctx, "error": repr(err)}
            )
            return DeliveryOutcome(503, "retry", code, "dead-letter write failed")
        ctx["fields"] = {"failed_delivery_uri": uri}
    log.error(f"webhook permanently rejected by Django{note}", extra=ctx)
    return DeliveryOutcome(200, "permanent_failure", code, snippet[:200])
