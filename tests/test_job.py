from __future__ import annotations

import json
import re

import cv2
import numpy as np
import pytest
import requests
from conftest import FAKE_TOKEN, encode, make_image

from condorin.core.detector import Detection
from condorin.job.config import JobSettings
from condorin.job.report import DeliveryError, Reporter
from condorin.job.runner import Runner, crop_png, list_images, main, shard

SCENE = "yaguas/2026-10-18T0645Z_s1.jpeg"
BOUNDS = {"sw": [-2.80, -71.00], "ne": [-2.70, -70.90]}


class StubDetector:
    device = "stub"

    def __init__(self, card, detections):
        self.card = card
        self.detections = detections

    def detect(self, image_bgr):
        return list(self.detections)


class RecordingReporter:
    def __init__(self):
        self.sent: list[tuple[dict, str]] = []

    def post(self, payload, key):
        self.sent.append((payload, key))
        return {"duplicate": False, "alerted": bool(payload["detections"])}


def put(bucket, name, meta=None, rgb=None):
    path = bucket / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(make_image() if rgb is None else rgb))
    if meta is not None:
        path.with_name(path.name + ".meta.json").write_text(json.dumps(meta))
    return path


def settings_for(bucket, **kw) -> JobSettings:
    return JobSettings(input_bucket=str(bucket), webhook_mode="log", **kw)


def runner(card, bucket, detections, **kw):
    reporter = RecordingReporter()
    r = Runner(settings_for(bucket, **kw), card, StubDetector(card, detections), reporter)
    return r, reporter


VESSEL = Detection("mining_vessel", 0.87, (640.0, 320.0, 680.0, 336.0))


def test_list_images_matches_prefix_and_skips_crops(tmp_path):
    put(tmp_path, SCENE)
    put(tmp_path, "yaguas/2026-10-19T0645Z_s1.jpeg")
    put(tmp_path, "yaguas-norte/2026-10-18T0645Z_s1.jpeg")
    put(tmp_path, "crops/yaguas/2026-10-18T0645Z_s1/1/v/000.png")
    (tmp_path / "yaguas" / "notes.txt").write_text("x")
    s = settings_for(tmp_path)
    assert list_images(s, "yaguas/2026-10-18") == [SCENE]
    assert list_images(s, "yaguas/") == [SCENE, "yaguas/2026-10-19T0645Z_s1.jpeg"]
    assert list_images(s, "crops/") == []


def test_shard_splits_without_overlap():
    items = [str(i) for i in range(10)]
    parts = [shard(items, i, 3) for i in range(3)]
    assert sorted(sum(parts, [])) == sorted(items)
    assert shard(items, 0, 1) == items


def test_reports_findings_with_contract_shape(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": json.dumps(BOUNDS)})
    weak = Detection("mining_vessel", 0.10, (10.0, 10.0, 30.0, 20.0))  # below review_low
    other = Detection("other_vessel", 0.99, (100.0, 100.0, 140.0, 120.0))
    r, rep = runner(card, tmp_path, [weak, VESSEL, other])
    summary = r.run([SCENE])

    assert (summary.processed, summary.with_findings, summary.failed) == (1, 1, 0)
    payload, key = rep.sent[0]
    img = payload["image"]
    assert key == f"local/{SCENE}#{img['generation']}"
    assert re.fullmatch(r"\d{1,32}", img["generation"])
    assert img | {"generation": "x"} == {
        "bucket": "local", "object": SCENE, "generation": "x", "river": "yaguas",
        "satellite": "SkyFi", "captured_at": "2026-10-18T06:45:00Z",
    }  # fmt: skip
    assert payload["model"] == {"name": card.name, "version": card.version}
    [d] = payload["detections"]
    assert d["confidence"] == 0.87 and d["bbox"] == [640, 320, 40, 16]
    assert all(isinstance(v, int) and v >= 0 for v in d["bbox"])
    # centre (660, 328) of a 1280x1280 scene inside BOUNDS
    assert d["lat"] == pytest.approx(-2.70 - 328 / 1280 * 0.10, abs=1e-6)
    assert d["lon"] == pytest.approx(-71.00 + 660 / 1280 * 0.10, abs=1e-6)
    assert d["lat"] != -2.7706 and d["lon"] != -70.9512  # never the demo point
    assert re.fullmatch(r"gs://[^/]+/.+#\d+", d["crop_uri"])
    crop_obj = d["crop_uri"].split("/", 3)[3].split("#")[0]
    assert (
        crop_obj == f"crops/yaguas/2026-10-18T0645Z_s1/{img['generation']}/{card.version}/scene.jpg"
    )
    assert (tmp_path / crop_obj).is_file()


# --- crop_uri modes -----------------------------------------------------------------------------

VESSEL2 = Detection("mining_vessel", 0.74, (100.0, 900.0, 140.0, 916.0))


def test_scene_boxed_is_the_default_and_shared_by_all_detections(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep = runner(card, tmp_path, [VESSEL, VESSEL2])
    r.run([SCENE])
    a, b = rep.sent[0][0]["detections"]
    assert a["crop_uri"] == b["crop_uri"] and a["crop_uri"].split("#")[0].endswith("/scene.jpg")
    path = tmp_path / a["crop_uri"].split("/", 3)[3].split("#")[0]
    img = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (1280, 1280)  # whole scene, not zoomed (already under 1600 px)
    for x1, y1, x2, y2 in (VESSEL.box, VESSEL2.box):  # a red box surrounds each detection
        ring = img[int(y1) - 9 : int(y2) + 9, int(x1) - 9 : int(x2) + 9]
        red = (ring[..., 2] > 200) & (ring[..., 1] < 80) & (ring[..., 0] < 80)
        assert red.sum() > 50


def test_scene_boxed_downscales_large_scenes(card):
    from condorin.job.runner import boxed_scene_jpeg

    big = np.full((2000, 2560, 3), 90, np.uint8)
    out = cv2.imdecode(np.frombuffer(boxed_scene_jpeg(big, [(1000, 1000, 1040, 1016)], 1600),
                                     np.uint8), cv2.IMREAD_COLOR)  # fmt: skip
    assert out.shape[:2] == (1250, 1600)  # longest side 1600, aspect kept
    red = (out[..., 2] > 200) & (out[..., 1] < 80) & (out[..., 0] < 80)
    x1, y1, x2, y2 = (round(v * 0.625) for v in (1000, 1000, 1040, 1016))  # box in the 1600 px copy
    assert red[y1 - 20 : y2 + 20, x1 - 20 : x2 + 20].sum() > 50  # drawn around the scaled box
    assert red[: y1 - 80].sum() == 0 and red[y2 + 30 :].sum() == 0  # label above, nothing else


def test_scene_boxed_is_written_once(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep = runner(card, tmp_path, [VESSEL])
    r.run([SCENE])
    r.run([SCENE])
    first, second = (p["detections"][0]["crop_uri"] for p, _ in rep.sent)
    assert first == second


def test_crop_mode_keeps_close_ups(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep = runner(card, tmp_path, [VESSEL, VESSEL2], crop_mode="crop")
    r.run([SCENE])
    uris = [d["crop_uri"].split("#")[0] for d in rep.sent[0][0]["detections"]]
    assert [u.rsplit("/", 1)[1] for u in uris] == ["000.png", "001.png"]


def test_no_scene_image_without_detections(tmp_path, card):
    put(tmp_path, SCENE)
    r, _ = runner(card, tmp_path, [])
    r.run([SCENE])
    assert not (tmp_path / "crops").exists()


def test_reports_empty_scene(tmp_path, card):
    put(tmp_path, SCENE)  # no bounds needed when nothing is found
    r, rep = runner(card, tmp_path, [])
    summary = r.run([SCENE])
    assert (summary.processed, summary.without_findings, summary.failed) == (1, 1, 0)
    assert rep.sent[0][0]["detections"] == []


def test_findings_without_bounds_are_not_reported_as_empty(tmp_path, card):
    put(tmp_path, SCENE)
    r, rep = runner(card, tmp_path, [VESSEL])
    summary = r.run([SCENE])
    assert rep.sent == []
    assert summary.failed == 1 and summary.failures == {"no_bounds": 1}


def test_metadata_overrides_and_missing_fields(tmp_path, card):
    put(
        tmp_path,
        "yaguas/scene.jpeg",
        {"captured_at": "2026-10-17T10:00:00Z", "satellite": "Pléiades"},
    )
    put(tmp_path, "yaguas/undated.jpeg")
    put(tmp_path, "flat.jpeg")
    r, rep = runner(card, tmp_path, [])
    summary = r.run(["yaguas/scene.jpeg", "yaguas/undated.jpeg", "flat.jpeg"])
    assert rep.sent[0][0]["image"]["satellite"] == "Pléiades"
    assert rep.sent[0][0]["image"]["captured_at"] == "2026-10-17T10:00:00Z"
    assert summary.processed == 1
    assert summary.failures == {"no_captured_at": 1, "no_river": 1}


def test_qc_rejection_is_failed_not_reported(tmp_path, card):
    p = tmp_path / SCENE
    p.parent.mkdir(parents=True)
    p.write_bytes(b"not an image")
    r, rep = runner(card, tmp_path, [])
    summary = r.run([SCENE])
    assert rep.sent == [] and summary.failures == {"rejected_qc": 1}


def test_rerun_keeps_the_first_crop(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep = runner(card, tmp_path, [VESSEL])
    r.run([SCENE])
    r.run([SCENE])
    first, second = (p["detections"][0]["crop_uri"] for p, _ in rep.sent)
    assert first == second


def test_crop_png_min_side_and_clamp():
    img = make_image(300, 200)[..., ::-1].copy()
    import cv2
    import numpy as np

    out = cv2.imdecode(np.frombuffer(crop_png(img, (0, 0, 10, 10), 4, 128), np.uint8), 1)
    assert out.shape[:2] == (69, 69)  # clamped at the top-left corner
    out = cv2.imdecode(np.frombuffer(crop_png(img, (100, 80, 110, 90), 4, 128), np.uint8), 1)
    assert out.shape[:2] == (128, 128)


# --- Reporter -----------------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data, headers, timeout):
        self.calls.append({"url": url, "data": data, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reporter(responses, **kw):
    s = JobSettings(webhook_mode="post", **kw)
    session = FakeSession(responses)
    tokens = []

    def fetch(aud):
        tokens.append(aud)
        return f"id-token-{len(tokens)}"

    return Reporter(s, session=session, token_fetcher=fetch, sleep=lambda _: None), session, tokens


def test_reporter_sends_id_token_and_idempotency_key():
    rep, session, tokens = reporter([FakeResponse(201, {"id": 1, "duplicate": False})])
    assert rep.post({"a": 1}, "river-images/x#1") == {"id": 1, "duplicate": False}
    h = session.calls[0]["headers"]
    assert h["Authorization"] == "Bearer id-token-1" and h["Idempotency-Key"] == "river-images/x#1"
    assert tokens == ["https://api.condorin.pe/api/v1/detections"]
    assert session.calls[0]["data"] == b'{"a":1}'


def test_reporter_retries_5xx_and_transport_then_succeeds():
    rep, session, _ = reporter(
        [
            requests.ConnectionError("boom"),
            FakeResponse(503),
            FakeResponse(200, {"duplicate": True}),
        ]
    )
    assert rep.post({}, "k")["duplicate"] is True
    assert len(session.calls) == 3


def test_reporter_does_not_retry_validation_errors():
    body = {"message": "bad", "type": "validation_error", "field_errors": {"image": ["x"]}}
    rep, session, _ = reporter([FakeResponse(400, body)])
    with pytest.raises(DeliveryError) as exc:
        rep.post({}, "k")
    assert exc.value.status == 400 and exc.value.body == body and len(session.calls) == 1


def test_reporter_refreshes_token_once_on_401():
    rep, session, tokens = reporter([FakeResponse(401), FakeResponse(201)])
    rep.post({}, "k")
    assert len(tokens) == 2 and session.calls[1]["headers"]["Authorization"] == "Bearer id-token-2"


def test_reporter_shared_secret_fallback():
    rep, session, tokens = reporter([FakeResponse(201)], detections_shared_secret=FAKE_TOKEN)
    rep.post({}, "k")
    assert tokens == [] and session.calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


# --- main ---------------------------------------------------------------------------------------


def test_main_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_BUCKET", str(tmp_path))
    monkeypatch.delenv("PREFIX", raising=False)
    assert main() == 2  # empty prefix
    monkeypatch.setenv("PREFIX", "yaguas/")
    monkeypatch.setenv("FAKE_MODEL", "1")
    monkeypatch.setenv("WEBHOOK_MODE", "post")
    assert main() == 2  # fake model never posts
    monkeypatch.setenv("FAKE_MODEL", "0")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "nomodel"))
    assert main() == 2  # no model card


def test_main_end_to_end_fake_model(monkeypatch, tmp_path, capsys):
    for i in range(3):
        put(tmp_path, f"yaguas/2026-10-18T06{i}0Z_s1.jpeg", {"bounds": BOUNDS}, make_image(seed=i))
    monkeypatch.setenv("INPUT_BUCKET", str(tmp_path))
    monkeypatch.setenv("PREFIX", "yaguas/2026-10-18")
    monkeypatch.setenv("FAKE_MODEL", "1")
    monkeypatch.setenv("WEBHOOK_MODE", "log")
    assert main() == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    done = lines[-1]
    assert done["message"].startswith("done: 3 reported")
    assert done["processed"] == 3 and done["failed"] == 0 and done["listed"] == 3


# --- time budget, run report, GSD ---------------------------------------------------------------


def test_budget_stops_before_the_deadline(tmp_path, card):
    names = [f"yaguas/2026-10-18T06{i}0Z_s1.jpeg" for i in range(3)]
    for n in names:
        put(tmp_path, n)
    r, rep = runner(card, tmp_path, [])
    summary = r.run(names, deadline=0.0)  # already past: nothing starts
    assert rep.sent == [] and summary.failures == {"not_started": 3}
    assert [x["object"] for x in summary.not_reported] == names
    summary = r.run(names, deadline=float("inf"))
    assert summary.processed == 3 and summary.failed == 0


def test_budget_leaves_room_for_the_slowest_image(tmp_path, card, monkeypatch):
    names = [f"yaguas/2026-10-18T06{i}0Z_s1.jpeg" for i in range(3)]
    for n in names:
        put(tmp_path, n)
    clock = {"t": 0.0}
    monkeypatch.setattr("condorin.job.runner.time.monotonic", lambda: clock["t"])
    r, rep = runner(card, tmp_path, [])
    real = r.process

    def slow(obj):
        clock["t"] += 40.0  # every image takes 40 s
        return real(obj)

    r.process = slow
    summary = r.run(names, deadline=100.0)  # 2 images fit (80 s); a 3rd would end at 120 s
    assert summary.processed == 2 and summary.failures == {"not_started": 1}
    assert summary.not_reported == [
        {"object": names[2], "reason": "not_started", "detail": "task time budget reached"}
    ]


def test_not_reported_lists_every_failure(tmp_path, card):
    put(tmp_path, SCENE)
    put(tmp_path, "flat.jpeg")
    r, _ = runner(card, tmp_path, [VESSEL])
    summary = r.run([SCENE, "flat.jpeg"])
    assert {(x["object"], x["reason"]) for x in summary.not_reported} == {
        (SCENE, "no_bounds"), ("flat.jpeg", "no_river")}  # fmt: skip
    assert "not_reported" not in summary.as_fields()


def test_main_writes_the_run_report(monkeypatch, tmp_path, capsys):
    put(tmp_path, "yaguas/2026-10-18T0600Z_s1.jpeg", {"bounds": BOUNDS})
    bad = tmp_path / "yaguas/2026-10-18T0610Z_s1.jpeg"
    bad.write_bytes(b"not an image")
    monkeypatch.setenv("INPUT_BUCKET", str(tmp_path))
    monkeypatch.setenv("PREFIX", "yaguas/2026-10-18")
    monkeypatch.setenv("FAKE_MODEL", "1")
    monkeypatch.setenv("WEBHOOK_MODE", "log")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "condorin-detector-abc")
    assert main() == 1
    report_path = tmp_path / "reports/condorin-detector-abc/task-000.json"
    report = json.loads(report_path.read_text())
    assert (
        report["execution"] == "condorin-detector-abc" and report["prefix"] == "yaguas/2026-10-18"
    )
    assert report["summary"]["processed"] == 1 and report["summary"]["failed"] == 1
    assert report["not_reported"][0]["object"] == "yaguas/2026-10-18T0610Z_s1.jpeg"
    assert report["not_reported"][0]["reason"] == "rejected_qc"
    done = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert done["report"] == str(report_path)
    # reports/ is never listed as input
    assert list_images(settings_for(tmp_path), "") == [
        "yaguas/2026-10-18T0600Z_s1.jpeg", "yaguas/2026-10-18T0610Z_s1.jpeg"]  # fmt: skip


def test_report_can_be_turned_off(monkeypatch, tmp_path):
    put(tmp_path, "yaguas/2026-10-18T0600Z_s1.jpeg", {"bounds": BOUNDS})
    for k, v in {"INPUT_BUCKET": str(tmp_path), "PREFIX": "yaguas/", "FAKE_MODEL": "1",
                 "WEBHOOK_MODE": "log", "REPORTS_PREFIX": ""}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    assert main() == 0 and not (tmp_path / "reports").exists()


def test_gsd_from_metadata_reaches_qc(tmp_path, card):
    strict = card.model_copy(update={"qc": card.qc.model_copy(update={"expected_gsd_m": 0.5})})
    put(tmp_path, "yaguas/2026-10-18T0600Z_s1.jpeg", {"gsd_m": "0.5"})
    put(tmp_path, "yaguas/2026-10-18T0610Z_s1.jpeg", {"gsd_m": 3.0})
    put(tmp_path, "yaguas/2026-10-18T0620Z_s1.jpeg", {"gsd_m": "half a metre"})
    put(tmp_path, "yaguas/2026-10-18T0630Z_s1.jpeg")
    r, rep = runner(strict, tmp_path, [])
    summary = r.run([f"yaguas/2026-10-18T06{i}0Z_s1.jpeg" for i in range(4)])
    assert summary.processed == 2  # matching GSD, and unknown GSD (check skipped)
    assert summary.failures == {"rejected_qc": 1, "bad_gsd_m": 1}
    mismatch = next(x for x in summary.not_reported if x["reason"] == "rejected_qc")
    assert "gsd_mismatch" in mismatch["detail"]
    assert summary.gsd_unchecked == 1


def test_gsd_ignored_when_the_card_has_no_expectation(tmp_path, card):
    put(tmp_path, SCENE, {"gsd_m": 3.0})
    r, _ = runner(card, tmp_path, [])
    summary = r.run([SCENE])
    assert summary.processed == 1 and summary.gsd_unchecked == 0
