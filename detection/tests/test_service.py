from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from conftest import encode, make_image
from fastapi.testclient import TestClient

from condorin.config import Settings
from condorin.core.detector import Detection, FakeDetector
from condorin.core.model_card import ModelCard
from condorin.io import storage
from condorin.service.app import create_app
from condorin.service.schemas import parse_detect_body
from condorin.service.tasks import WebhookEnqueuer

NAME = "2026-10-15T1042Z_tile_r000_c000_sw_-2.782003_-70.977122_ne_-2.772959_-70.968128.jpg"


class StubDetector:
    def __init__(self, detections: list[Detection]):
        self.card = ModelCard.placeholder()
        self.device = "stub"
        self.detections = detections
        self.calls = 0

    def detect(self, image_bgr):
        self.calls += 1
        return list(self.detections)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    out = tmp_path / "out"
    return Settings(
        fake_model=True,
        model_dir=str(tmp_path / "no-model"),
        results_uri_prefix=str(out / "results"),
        overlay_uri_prefix=str(out / "overlays"),
        batches_uri_prefix=str(out / "batches"),
        failed_deliveries_uri_prefix=str(out / "failed"),
        webhook_mode="log",
        detect_mode="direct",
        audit_rate=0.0,
    )


def write_image(root: Path, name: str = NAME, w: int = 1280, h: int = 1280, seed: int = 0) -> str:
    path = root / "river-images" / "yaguas" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(make_image(w, h, seed)))
    return str(path)


def client_for(settings, detector=None) -> tuple[TestClient, WebhookEnqueuer]:
    webhook = WebhookEnqueuer(settings)
    app = create_app(settings, detector=detector, webhook=webhook)
    return TestClient(app), webhook


def test_root_health_ready(settings):
    c, _ = client_for(settings)
    with c:
        assert c.get("/healthz").json() == {"status": "ok"}
        assert c.get("/readyz").json()["ready"] is True
        root = c.get("/").json()
        assert (
            root["source"].startswith("https://github.com/") and root["license"] == "AGPL-3.0-only"
        )


def test_detect_writes_result_and_skips_recompute(settings, tmp_path):
    uri = write_image(tmp_path)
    det = FakeDetector(ModelCard.placeholder())
    c, _ = client_for(settings, det)
    with c:
        r1 = c.post("/detect", json={"image_uri": uri, "job_id": "j1"})
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["status"] == "ok" and body["cached"] is False
        assert body["decision"] in ("detected", "needs_review", "clear")
        assert storage.exists(body["result_uri"])
        assert body["image"]["river"] == "yaguas"
        assert body["image"]["captured_at"] == "2026-10-15T10:42:00Z"
        assert body["image"]["bounds"]["sw"] == [-2.782003, -70.977122]
        r2 = c.post("/detect", json={"image_uri": "file://" + uri, "job_id": "j2"})
        assert r2.status_code == 200 and r2.json()["cached"] is True
        assert det.calls == 1  # no recompute


def test_detect_positive_sends_webhook_and_overlay(settings, tmp_path):
    uri = write_image(tmp_path)
    det = StubDetector([
        Detection("mining_vessel", 0.91, (1140, 1041, 1185, 1098)),
        Detection("mining_vessel", 0.10, (10, 10, 40, 20)),
        Detection("other_vessel", 0.80, (500, 500, 520, 530)),
    ])  # fmt: skip
    c, webhook = client_for(settings, det)
    with c:
        body = c.post("/detect", json={"image_uri": uri}).json()
    assert body["decision"] == "detected" and body["score"] == 0.91
    assert body["webhook"]["sent"] is True and body["webhook"]["task"].startswith("deliver-")
    assert storage.exists(body["artifacts"]["overlay"])
    (event,) = webhook.events
    assert event["idempotency_key"] == body["idempotency_key"]
    assert event["idempotency_key"].startswith("local/") and "#" in event["idempotency_key"]
    dets = event["payload"]["detections"]
    assert len(dets) == 1  # only mining_vessel >= review_low
    assert dets[0]["bbox"] == [1140, 1041, 45, 57]
    assert dets[0]["lat"] is not None and -2.782003 < dets[0]["lat"] < -2.772959
    assert -70.977122 < dets[0]["lon"] < -70.968128


def test_detect_no_detections_no_webhook(settings, tmp_path):
    uri = write_image(tmp_path)
    c, webhook = client_for(settings, StubDetector([]))
    with c:
        body = c.post("/detect", json={"image_uri": uri}).json()
    assert body["decision"] == "clear" and body["webhook"] == {
        "sent": False, "reason": "no_detections", "task": None}  # fmt: skip
    assert webhook.events == [] and body["artifacts"] == {}


def test_audit_sample(settings, tmp_path):
    uri = write_image(tmp_path)
    settings.audit_rate = 1.0
    c, _ = client_for(settings, StubDetector([]))
    with c:
        assert c.post("/detect", json={"image_uri": uri}).json()["audit_sample"] is True


def test_qc_rejection_is_200(settings, tmp_path):
    uri = write_image(tmp_path, "small.jpg", 400, 400)
    c, webhook = client_for(settings)
    with c:
        r = c.post("/detect", json={"image_uri": uri})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected_qc" and body["qc"]["reasons"] == ["too_small"]
    assert "decision" in body and body["decision"] is None
    assert body["webhook"]["reason"] == "rejected_qc" and webhook.events == []


def test_unsupported_format_rejected(settings, tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"GIF89a" + b"\x00" * 100)
    c, _ = client_for(settings)
    with c:
        body = c.post("/detect", json={"image_uri": str(p)}).json()
    assert body["status"] == "rejected_qc" and body["qc"]["reasons"] == ["unsupported_format"]


def test_pubsub_envelope(settings, tmp_path):
    uri = write_image(tmp_path)
    data = base64.b64encode(json.dumps({"image_uri": uri}).encode()).decode()
    c, _ = client_for(settings)
    with c:
        r = c.post("/detect", json={"message": {"data": data, "messageId": "m-1"}})
    assert r.status_code == 200 and r.json()["job_id"] == "m-1"


def test_parse_gcs_notification_bodies():
    gcs = {"bucket": "river-images", "name": "yaguas/a.jpg", "generation": 17}
    data = base64.b64encode(json.dumps(gcs).encode()).decode()
    job = parse_detect_body({"message": {"data": data, "messageId": "9"}})
    assert job.image_uri == "gs://river-images/yaguas/a.jpg" and job.generation == "17"
    attrs = {"bucketId": "b", "objectId": "o.png", "objectGeneration": "5"}
    job = parse_detect_body({"message": {"attributes": attrs}})
    assert (job.image_uri, job.generation) == ("gs://b/o.png", "5")
    assert parse_detect_body(gcs).image_uri == "gs://river-images/yaguas/a.jpg"


def test_4xx_vs_5xx(settings, tmp_path, monkeypatch):
    c, _ = client_for(settings)
    missing = str(tmp_path / "missing.jpg")
    with c:
        assert c.post("/detect", content=b"not json").status_code == 400
        assert c.post("/detect", json={"options": {}}).status_code == 400
        assert c.post("/detect", json={"image_uri": "s3://x/y.jpg"}).status_code == 404
        assert c.post("/detect", json={"image_uri": missing}).status_code == 404
        # pinned generation that no longer exists: recorded as failed, 200 (no endless retries)
        r = c.post("/detect", json={"image_uri": missing, "generation": "123"})
        assert r.status_code == 200 and r.json()["status"] == "failed"

        uri = write_image(tmp_path)

        def boom(*a, **k):
            raise storage.Transient("gcs 503")

        monkeypatch.setattr(storage, "read_bytes", boom)
        assert c.post("/detect", json={"image_uri": uri}).status_code == 503


def test_budget_exceeded_is_503(settings, tmp_path):
    settings.request_budget_s = 0.0
    uri = write_image(tmp_path)
    c, _ = client_for(settings)
    with c:
        assert c.post("/detect", json={"image_uri": uri}).status_code == 503
        assert not storage.list_uris(settings.results_uri_prefix)  # nothing half-written


def test_batch_of_100(settings, tmp_path):
    root = tmp_path / "imgs"
    uris = [
        write_image(root, f"tile_r{i:03d}_c000_sw_-2.78_-70.97_ne_-2.77_-70.96.jpg", 704, 704, i)
        for i in range(101)
    ]
    c, _ = client_for(settings)
    with c:
        too_many = c.post("/batches", json={"images": [{"uri": u} for u in uris]})
        assert too_many.status_code == 422
        r = c.post("/batches", json={"batch_id": "b1", "images": [{"uri": u} for u in uris[:100]]})
        assert r.status_code == 202, r.text
        assert r.json() == {"batch_id": "b1", "total": 100, "accepted": 100,
                            "skipped_existing": 0, "not_found": 0}  # fmt: skip
        s = c.get("/batches/b1").json()
        assert s["complete"] is True and s["total"] == 100
        n = s["counts"]
        assert n["done"] == 100 and n["pending"] == 0 and n["ok"] == 100
        assert n["detected"] + n["needs_review"] + n["clear"] == 100
        again = c.post(
            "/batches", json={"batch_id": "b1", "images": [{"uri": u} for u in uris[:100]]}
        )
        assert again.json()["skipped_existing"] == 100 and again.json()["accepted"] == 0
        assert c.get("/batches/nope").status_code == 404
        assert c.get("/batches/..%2Fetc").status_code in (400, 404)


def test_batch_prefix_and_validation(settings, tmp_path):
    root = tmp_path / "imgs"
    for i in range(3):
        write_image(root, f"img{i}.jpg", 704, 704, i)
    (root / "river-images" / "yaguas" / "notes.txt").write_text("skip me")
    c, _ = client_for(settings)
    with c:
        r = c.post("/batches", json={"prefix": str(root), "limit": 2})
        assert r.status_code == 202 and r.json()["accepted"] == 2
        assert c.post("/batches", json={"prefix": str(root), "limit": 101}).status_code == 422
        assert c.post("/batches", json={}).status_code == 422
        bad = c.post("/batches", json={"images": [{"uri": str(root / "missing.jpg")}]})
        assert bad.status_code == 202 and bad.json()["not_found"] == 1
        s = c.get(f"/batches/{bad.json()['batch_id']}").json()
        assert s["counts"]["failed"] == 1
