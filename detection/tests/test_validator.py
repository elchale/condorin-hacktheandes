"""TypeSafe Jev validator: request shape and headers, retries, answer parsing, runner integration."""

from __future__ import annotations

import json
import logging

import cv2
import numpy as np
import pytest
import requests
from conftest import make_image
from pydantic import ValidationError
from test_job import BOUNDS, SCENE, RecordingReporter, StubDetector, put, settings_for

from condorin.core.detector import Detection
from condorin.job.config import JobSettings
from condorin.job.runner import Runner
from condorin.job.validator import (
    CRITERIA,
    JevValidator,
    ValidatorError,
    centre_crop,
    retry_delay,
)

KEY = "ts-test-key-not-real-0042"
STRONG = Detection("mining_vessel", 0.83, (640.0, 320.0, 680.0, 336.0))
STRONG2 = Detection("mining_vessel", 0.61, (100.0, 900.0, 130.0, 940.0))
WEAK = Detection("mining_vessel", 0.31, (1000.0, 1000.0, 1030.0, 1012.0))


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, files, timeout):
        self.calls.append({"url": url, "headers": headers, "files": files, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def answers(*nouls, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {f"candidate_{i}": {"type": "noul", "noul": n} for i, n in enumerate(nouls)},
        "usage": {"input_tokens": 1200, "output_tokens": 20},
    }


def settings(**kw) -> JobSettings:
    return JobSettings(jev_enabled=True, typesafe_api_key=KEY, **kw)


def validator(responses, sleeps=None, **kw):
    s = Session(responses)
    v = JevValidator(settings(**kw), session=s, sleep=(sleeps.append if sleeps is not None
                                                        else lambda _: None), rand=lambda: 0.0)  # fmt: skip
    return v, s


IMAGE = np.ascontiguousarray(make_image(1280, 1280)[..., ::-1])


# --- request ------------------------------------------------------------------------------------


def test_request_url_headers_and_multipart_body():
    v, s = validator([Resp(200, answers(0.9, 0.2))])
    verdicts = v.validate(IMAGE, [STRONG2, STRONG])  # sorted strongest first
    (call,) = s.calls
    assert call["url"] == "https://api.typesafe.ai/v1/systemone"
    assert call["headers"] == {
        "Authorization": f"Bearer {KEY}",
        "TypeSafe-Danger-Zone-Images": "true",
    }  # Content-Type is set by requests (multipart boundary), never by hand
    assert call["timeout"] == 60.0
    files = call["files"]
    name, (filename, body_json, ctype) = files[0]
    assert (name, filename, ctype) == ("request", None, "application/json")  # first part
    body = json.loads(body_json)
    assert body["model"] == "jev-1.13.0"  # pinned version, not the moving alias
    assert set(body["questions"]) == {"candidate_0", "candidate_1"}
    q = body["questions"]["candidate_0"]
    assert q["type"] == "noul" and q["criteria"] == CRITERIA
    assert "`candidates[0].crop`" in q["instructions"]
    refs = [c["crop"] for c in body["state"]["candidates"]]
    assert len(set(refs)) == 2 and set(refs) == set(body["assets"])
    serialized = json.dumps({k: body[k] for k in ("state", "questions")})
    for ref, asset in body["assets"].items():
        assert ref in serialized  # every asset is referenced (else the API answers 400)
        assert asset == {"type": "image", "part": asset["part"], "format": "png"}
    image_parts = {n: (fn, data, ct) for n, (fn, data, ct) in files[1:]}
    assert set(image_parts) == {a["part"] for a in body["assets"].values()}
    for _, data, ct in image_parts.values():
        assert ct == "image/png"
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[:2] == (768, 768)  # 384 px crop x2, within 280-1568
    assert [v.detection for v in verdicts] == [STRONG, STRONG2]
    assert [(v.noul, v.passed) for v in verdicts] == [(0.9, True), (0.2, False)]


def test_threshold_is_inclusive_and_configurable():
    v, _ = validator([Resp(200, answers(0.7, 0.69))])
    assert [x.passed for x in v.validate(IMAGE, [STRONG, STRONG2])] == [True, False]
    v, _ = validator([Resp(200, answers(0.69))], jev_min_noul=0.6)
    assert v.validate(IMAGE, [STRONG])[0].passed


def test_candidates_over_the_cap_are_not_sent_and_do_not_pass():
    v, s = validator([Resp(200, answers(0.95))], jev_max_candidates=1)
    verdicts = v.validate(IMAGE, [STRONG2, STRONG])
    body = json.loads(s.calls[0]["files"][0][1][1])
    assert list(body["questions"]) == ["candidate_0"] and len(body["assets"]) == 1
    assert [(x.detection, x.noul, x.passed) for x in verdicts] == [
        (STRONG, 0.95, True), (STRONG2, None, False)]  # fmt: skip


def test_centre_crop_keeps_the_object_centred_and_inside_the_image():
    img = np.zeros((1000, 1200, 3), np.uint8)
    img[495:505, 595:605] = 255  # object at (600, 500)
    crop = cv2.imdecode(np.frombuffer(centre_crop(img, (595, 495, 605, 505), 384, 1), np.uint8),
                        cv2.IMREAD_COLOR)  # fmt: skip
    ys, xs = np.nonzero(crop[..., 0])
    assert crop.shape[:2] == (384, 384) and abs(xs.mean() - 192) < 1 and abs(ys.mean() - 192) < 1
    edge = cv2.imdecode(np.frombuffer(centre_crop(img, (0, 0, 10, 10), 384, 2), np.uint8),
                        cv2.IMREAD_COLOR)  # fmt: skip
    assert edge.shape[:2] == (768, 768)  # shifted inside, not padded or shrunk
    with pytest.raises(ValueError, match="280-1568"):
        centre_crop(img, (0, 0, 10, 10), 200, 1)


def test_crop_size_is_validated_in_settings():
    with pytest.raises(ValidationError, match="280-1568"):
        JobSettings(jev_crop_px=1000, jev_upscale=2)
    with pytest.raises(ValidationError, match="280-1568"):
        JobSettings(jev_crop_px=128, jev_upscale=1)


def test_api_key_required():
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        JevValidator(JobSettings(jev_enabled=True))


# --- retries ------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 429, 500, 503, 529])
def test_retryable_statuses(status):
    sleeps = []
    v, s = validator([Resp(status, {"error": "busy"}), Resp(200, answers(0.9))], sleeps)
    assert v.validate(IMAGE, [STRONG])[0].passed
    assert len(s.calls) == 2 and sleeps == [0.5]


@pytest.mark.parametrize("status", [400, 401, 413, 415, 422])
def test_non_retryable_statuses_fail_at_once(status):
    v, s = validator([Resp(status, {"error": "nope"}), Resp(200, answers(0.9))])
    with pytest.raises(ValidatorError) as err:
        v.validate(IMAGE, [STRONG])
    assert err.value.status == status and len(s.calls) == 1


def test_retries_give_up_after_max_with_exponential_backoff():
    sleeps = []
    v, s = validator([Resp(529)] * 4, sleeps)
    with pytest.raises(ValidatorError, match="529"):
        v.validate(IMAGE, [STRONG])
    assert len(s.calls) == 4 and sleeps == [0.5, 1.0, 2.0]  # 3 retries, then give up


def test_connection_errors_are_retried():
    v, s = validator([requests.ConnectionError("down"), requests.Timeout("slow"),
                      Resp(200, answers(0.8))])  # fmt: skip
    assert v.validate(IMAGE, [STRONG])[0].passed and len(s.calls) == 3


def test_retry_after_headers_are_honoured():
    assert retry_delay(Resp(429, headers={"retry-after-ms": "1500"}), 1, lambda: 0) == 1.5
    assert retry_delay(Resp(429, headers={"retry-after": "3"}), 1, lambda: 0) == 3.0
    assert retry_delay(Resp(429, headers={"retry-after": "9999"}), 1, lambda: 0) == 60.0
    assert retry_delay(Resp(429, headers={"retry-after": "garbage"}), 2, lambda: 0) == 1.0
    assert retry_delay(None, 10, lambda: 0) == 5.0  # capped backoff
    assert retry_delay(None, 1, lambda: 1.0) == 0.375  # 25% jitter


def test_malformed_answers_fail():
    for body in ({"answers": {}}, {"answers": {"candidate_0": {"type": "choice"}}}):
        v, _ = validator([Resp(200, body)])
        with pytest.raises(ValidatorError, match="malformed"):
            v.validate(IMAGE, [STRONG])
    v, _ = validator([Resp(200, None)])
    with pytest.raises(ValidatorError, match="without JSON"):
        v.validate(IMAGE, [STRONG])


def test_key_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    v, _ = validator([Resp(401, {"error": "invalid key"})])
    with pytest.raises(ValidatorError) as err:
        v.validate(IMAGE, [STRONG])
    v2, _ = validator([Resp(200, answers(0.9))])
    v2.validate(IMAGE, [STRONG])
    assert KEY not in caplog.text and KEY not in str(err.value)


# --- runner -------------------------------------------------------------------------------------


def runner_with(tmp_path, card, detections, responses):
    reporter = RecordingReporter()
    v, s = validator(responses)
    r = Runner(settings_for(tmp_path), card, StubDetector(card, detections), reporter, v)
    return r, reporter, s


def test_runner_reports_only_confirmed_strong_detections(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep, s = runner_with(tmp_path, card, [STRONG, STRONG2, WEAK],
                            [Resp(200, answers(0.91, 0.4))])  # fmt: skip
    summary = r.run([SCENE])
    sent = rep.sent[0][0]["detections"]
    assert [d["confidence"] for d in sent] == [0.83, 0.31]  # confirmed + weak (never sent to Jev)
    body = json.loads(s.calls[0]["files"][0][1][1])
    assert len(body["questions"]) == 2  # only the two >= 0.5
    assert summary.jev_confirmed == 1 and summary.jev_rejected == 1
    assert summary.jev_rejections == [{
        "object": SCENE, "confidence": 0.61, "noul": 0.4,
        "box_xyxy": [100.0, 900.0, 130.0, 940.0], "reason": "below_min_noul"}]  # fmt: skip


def test_runner_all_rejected_reports_the_scene_without_strong_findings(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep, _ = runner_with(tmp_path, card, [STRONG], [Resp(200, answers(0.1))])
    summary = r.run([SCENE])
    assert rep.sent[0][0]["detections"] == [] and summary.without_findings == 1


def test_runner_skips_jev_when_nothing_reaches_the_trigger(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep, s = runner_with(tmp_path, card, [WEAK], [])
    r.run([SCENE])
    assert s.calls == [] and len(rep.sent[0][0]["detections"]) == 1


def test_runner_fails_closed_when_jev_is_unavailable(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    r, rep, _ = runner_with(tmp_path, card, [STRONG], [Resp(401, {"error": "bad key"})])
    summary = r.run([SCENE])
    assert rep.sent == [] and summary.failures == {"jev_unavailable": 1}
    assert "401" in summary.not_reported[0]["detail"]


def test_runner_without_validator_is_unchanged(tmp_path, card):
    put(tmp_path, SCENE, {"bounds": BOUNDS})
    reporter = RecordingReporter()
    Runner(settings_for(tmp_path), card, StubDetector(card, [STRONG]), reporter).run([SCENE])
    assert reporter.sent[0][0]["detections"][0]["confidence"] == 0.83


def test_main_refuses_jev_without_a_key(monkeypatch, tmp_path):
    from condorin.job.runner import main

    for k, v in {"INPUT_BUCKET": str(tmp_path), "PREFIX": "yaguas/", "FAKE_MODEL": "1",
                 "WEBHOOK_MODE": "log", "JEV_ENABLED": "1"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert main() == 2
