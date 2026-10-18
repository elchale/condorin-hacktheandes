from __future__ import annotations

import json
import logging

import httpx
import pytest
from conftest import FAKE_TOKEN
from fastapi.testclient import TestClient
from pydantic import SecretStr

from condorin.config import Settings
from condorin.io import storage
from condorin.logs import JsonFormatter
from condorin.notifier.app import create_app
from condorin.notifier.delivery import deliver, failed_delivery_uri
from condorin.notifier.payload import build_webhook_payload, serialize

URL = "https://django.test/api/v1/detections"
KEY = "river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"

# Appendix B1, verbatim body
B1 = json.loads("""{
    "image": {
      "bucket": "river-images",
      "object": "yaguas/2026-10-15T1042Z_s1.jpeg",
      "generation": "1792297654023751",
      "river": "yaguas",
      "satellite": "Skyfi",
      "captured_at": "2026-10-15T10:42:00Z"
    },
    "model": {"name": "dredge-detector", "version": "v0.3"},
    "detections": [
      {"lat": -2.7706, "lon": -70.9512, "confidence": 0.87,
       "bbox": [412, 318, 14, 9],
       "crop_uri": "gs://river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"}
    ]
  }""")


def result(**over) -> dict:
    r = {
        "schema_version": 1,
        "status": "ok",
        "idempotency_key": KEY,
        "positive_class": "mining_vessel",
        "image": {"bucket": "river-images", "object": "yaguas/2026-10-15T1042Z_s1.jpeg",
                  "generation": "1792297654023751", "width": 2560, "height": 2560,
                  "river": "yaguas", "satellite": "Skyfi", "captured_at": "2026-10-15T10:42:00Z",
                  "bounds": None},
        "model": {"name": "dredge-detector", "version": "v0.3",
                  "thresholds": {"detect": 0.62, "review_low": 0.25}},
        "detections": [
            {"class": "other_vessel", "confidence": 0.95, "bbox_xyxy": [1, 1, 30, 10],
             "lat": -2.7, "lon": -70.9},
            {"class": "mining_vessel", "confidence": 0.87, "bbox_xyxy": [412.2, 318.0, 426.3, 327.1],
             "lat": -2.7706, "lon": -70.9512},
            {"class": "mining_vessel", "confidence": 0.1, "bbox_xyxy": [5, 5, 40, 20],
             "lat": -2.7, "lon": -70.9},
        ],
    }  # fmt: skip
    r.update(over)
    return r


def test_payload_matches_appendix_b1_exactly():
    payload = build_webhook_payload(result())
    assert payload == B1
    assert serialize(payload) == serialize(B1)  # same key order too


def test_payload_when_not_to_send():
    assert build_webhook_payload(result(status="rejected_qc")) is None
    assert build_webhook_payload(result(status="failed")) is None
    assert build_webhook_payload(result(detections=[])) is None
    assert build_webhook_payload(result(), min_confidence=0.9) is None
    empty = build_webhook_payload(result(detections=[]), send_empty=True)
    assert empty["detections"] == [] and empty["image"] == B1["image"]


def event() -> dict:
    return {"idempotency_key": KEY, "payload": B1, "model_version": "v0.3"}


def run(handler, tmp_path) -> tuple:
    seen = []

    def h(request: httpx.Request):
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(h))
    out = deliver(event(), url=URL, token=FAKE_TOKEN, client=client,
                  failed_prefix=str(tmp_path / "failed"))  # fmt: skip
    return out, seen


@pytest.mark.parametrize(
    "code,http_status,outcome,dead_letter",
    [
        (200, 200, "delivered", False),
        (201, 200, "delivered", False),
        (400, 200, "permanent_failure", True),
        (401, 503, "auth_rejected", False),
        (403, 503, "auth_rejected", False),
        (409, 200, "permanent_failure", True),
        (422, 200, "permanent_failure", True),
        (408, 503, "retry", False),
        (429, 503, "retry", False),
        (500, 503, "retry", False),
        (502, 503, "retry", False),
    ],
)
def test_delivery_status_branches(tmp_path, code, http_status, outcome, dead_letter):
    out, seen = run(lambda r: httpx.Response(code, text="nope"), tmp_path)
    assert (out.http_status, out.result, out.django_status) == (http_status, outcome, code)
    assert len(seen) == 1
    dl = failed_delivery_uri(str(tmp_path / "failed"), KEY)
    assert storage.exists(dl) is dead_letter
    if dead_letter:
        rec = storage.read_json(dl)
        assert rec["status"] == code and rec["event"]["payload"] == B1


def test_delivery_timeout_retries(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    out, _ = run(timeout, tmp_path)
    assert (out.http_status, out.result) == (503, "retry")


def test_headers_and_body_bytes(tmp_path):
    out, (req,) = run(lambda r: httpx.Response(200), tmp_path)
    assert req.method == "POST" and str(req.url) == URL
    assert req.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert req.headers["Idempotency-Key"] == KEY
    assert req.headers["Content-Type"] == "application/json"
    transport_defaults = {"host", "accept", "accept-encoding", "connection", "user-agent",
                          "content-length"}  # fmt: skip
    ours = {k.lower() for k in req.headers} - transport_defaults
    assert ours == {"authorization", "idempotency-key", "content-type"}
    assert req.content == serialize(B1)
    assert json.loads(req.content) == B1


def test_token_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    for code in (200, 400, 401, 409, 429, 500):
        run(
            lambda r, c=code: httpx.Response(c, text=f"echo {r.headers['Authorization']}"), tmp_path
        )
    fmt = JsonFormatter()
    text = "\n".join(fmt.format(r) for r in caplog.records)
    assert caplog.records and "webhook auth rejected" in text
    assert FAKE_TOKEN not in text.replace(f"echo Bearer {FAKE_TOKEN}", "")  # only Django's echo
    assert "Authorization" not in text


def test_notifier_app(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201)

    s = Settings(webhook_url=URL, webhook_token=SecretStr(FAKE_TOKEN),
                 failed_deliveries_uri_prefix=str(tmp_path / "failed"))  # fmt: skip
    app = create_app(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with TestClient(app) as c:
        assert c.get("/readyz").status_code == 200
        r = c.post("/deliver", json={"event": event()})
        assert r.status_code == 200 and r.json()["result"] == "delivered"
        assert calls[0].content == serialize(B1)
        assert c.post("/deliver", json={"nope": 1}).status_code == 400

    unconfigured = create_app(Settings(webhook_url=None, webhook_token=None))
    with TestClient(unconfigured) as c:
        assert c.get("/readyz").status_code == 503
        assert c.post("/deliver", json={"event": event()}).status_code == 503
