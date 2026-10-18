"""Final validation of strong detections with TypeSafe's Jev (a System One model).

Detections at or above `JEV_TRIGGER_CONFIDENCE` are only reported when Jev confirms them: one
request per scene, one image crop per candidate, one Noul question per candidate ("is the object
at the centre a mining dredge or barge?"). A candidate passes when its `noul` is at least
`JEV_MIN_NOUL`.

HTTP contract (https://docs.typesafe.ai/api, /images, /models, /sdk/python/api/retries):

    POST {TYPESAFE_BASE_URL}/v1/systemone
    Authorization: Bearer <TYPESAFE_API_KEY>
    TypeSafe-Danger-Zone-Images: true          # required for any request with an image
    Content-Type: multipart/form-data           # set by requests: part "request" = JSON body,
                                                # one image part per asset (recommended for images)

Images must be PNG/JPEG with each side 280-1568 px. The model is pinned to a versioned ID because
the thresholds are tuned against one version (the `jev-latest` alias moves). Retries follow the
official SDK: 408, 429 and 5xx (529 = overloaded) with exponential backoff, honouring `Retry-After`
and `retry-after-ms`. Other statuses (400, 401, 413, 415, 422) are not retried. The key is never
logged.

Images are a "Dreamer-ready" (beta) feature of the API: request format and accuracy may change.
"""

from __future__ import annotations

import email.utils
import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
import requests

from condorin.core.detector import Detection

log = logging.getLogger(__name__)

IMAGE_MIN_SIDE = 280  # API limits for each image side, inclusive
IMAGE_MAX_SIDE = 1568
RETRY_STATUSES = {408, 429, *range(500, 600)}
BACKOFF_INITIAL_S = 0.5
BACKOFF_MAX_S = 5.0
RETRY_AFTER_MAX_S = 60.0

CONTEXT = (
    "Each crop is an overhead satellite image (about 0.5 m per pixel) of a river in the Peruvian "
    "Amazon, centred on an object that a detector flagged as a possible illegal gold-mining dredge "
    "or barge."
)
QUESTION = "Is the object at the centre of `candidates[{i}].crop` an illegal-mining dredge or mining barge?"
CRITERIA = {
    "true": (
        "A mining dredge or barge: a boxy, flat hull larger than a canoe, usually dark or with a "
        "roof or machinery, on the river channel or moored at the bank; it may have pipes, rafts "
        "or a muddy sediment plume next to it."
    ),
    "false": (
        "Not a dredge or barge: a small boat or canoe, a log, a sandbar, a bank notch, a shadow, a "
        "cloud, vegetation, a building on land, or nothing in particular."
    ),
}


class ValidatorError(Exception):
    """Jev could not answer (after retries, or a non-retryable status)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Verdict:
    detection: Detection
    noul: float | None  # None: not checked (over JEV_MAX_CANDIDATES)
    passed: bool


def centre_crop(image_bgr: np.ndarray, box: tuple[float, ...], side: int, upscale: int) -> bytes:
    """A `side`-px square centred on the box (shifted to stay inside the image), scaled by
    `upscale`, as PNG. The detected object stays at the centre, which the question refers to."""
    h, w = image_bgr.shape[:2]
    side = min(side, h, w)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x0 = int(min(max(round(cx - side / 2), 0), w - side))
    y0 = int(min(max(round(cy - side / 2), 0), h - side))
    crop = image_bgr[y0 : y0 + side, x0 : x0 + side]
    if upscale > 1:
        crop = cv2.resize(crop, (side * upscale, side * upscale), interpolation=cv2.INTER_CUBIC)
    out_side = crop.shape[0]
    if not IMAGE_MIN_SIDE <= out_side <= IMAGE_MAX_SIDE:
        raise ValueError(f"crop side {out_side}px is outside the API's {IMAGE_MIN_SIDE}-"
                         f"{IMAGE_MAX_SIDE}px range")  # fmt: skip
    ok, buf = cv2.imencode(".png", crop)
    if not ok:  # pragma: no cover
        raise ValueError("PNG encoding failed")
    return buf.tobytes()


def retry_delay(resp: requests.Response | None, attempt: int, rand: Callable[[], float]) -> float:
    """Delay before retry number `attempt` (1-based): the server's Retry-After / retry-after-ms
    when present, else exponential backoff with 25% jitter (as in the SDK's RetryPolicy)."""
    headers = resp.headers if resp is not None else {}
    ms = headers.get("retry-after-ms")
    if ms:
        try:
            return min(max(float(ms) / 1000, 0.0), RETRY_AFTER_MAX_S)
        except ValueError:
            pass
    ra = headers.get("retry-after")
    if ra:
        try:
            return min(max(float(ra), 0.0), RETRY_AFTER_MAX_S)
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(ra)  # HTTP-date form
            except (TypeError, ValueError):
                when = None
            if when is not None:
                return min(max(when.timestamp() - time.time(), 0.0), RETRY_AFTER_MAX_S)
    base = min(BACKOFF_INITIAL_S * 2 ** (attempt - 1), BACKOFF_MAX_S)
    return base * (1 - 0.25 * rand())


class JevValidator:
    def __init__(
        self,
        settings,  # condorin.job.config.JobSettings
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        if settings.typesafe_api_key is None or not settings.typesafe_api_key.get_secret_value():
            raise ValueError("JEV_ENABLED=1 needs TYPESAFE_API_KEY (from Secret Manager)")
        self.settings = settings
        self.session = session or requests.Session()
        self.sleep = sleep
        self.rand = rand
        self.url = settings.typesafe_base_url.rstrip("/") + "/v1/systemone"

    def build_request(
        self, image_bgr: np.ndarray, candidates: list[Detection]
    ) -> tuple[dict, list]:
        """The JSON body and the multipart image parts for one scene's candidates."""
        s = self.settings
        state: dict = {"context": CONTEXT, "candidates": []}
        assets: dict = {}
        parts: list = []
        questions: dict = {}
        for i, d in enumerate(candidates):
            ref = f"crop-{uuid.uuid4()}"  # unique: references are matched as plain text
            part = f"image-{i}"
            png = centre_crop(image_bgr, d.box, s.jev_crop_px, s.jev_upscale)
            state["candidates"].append({"crop": ref})
            assets[ref] = {"type": "image", "part": part, "format": "png"}
            parts.append((part, (f"{part}.png", png, "image/png")))
            questions[f"candidate_{i}"] = {
                "type": "noul",
                "instructions": QUESTION.format(i=i),
                "criteria": CRITERIA,
            }
        body = {"model": s.jev_model, "state": state, "assets": assets, "questions": questions}
        return body, parts

    def ask(self, body: dict, parts: list) -> dict:
        """POST the multipart request with retries. Returns the parsed JSON response."""
        s = self.settings
        headers = {
            "Authorization": f"Bearer {s.typesafe_api_key.get_secret_value()}",
            "TypeSafe-Danger-Zone-Images": "true",
        }
        request_part = ("request", (None, json.dumps(body, ensure_ascii=False), "application/json"))
        error = ValidatorError("not attempted")
        for attempt in range(s.jev_max_retries + 1):
            resp = None
            try:
                resp = self.session.post(self.url, headers=headers, files=[request_part, *parts],
                                         timeout=s.jev_timeout_s)  # fmt: skip
            except requests.RequestException as err:
                error = ValidatorError(f"TypeSafe unreachable: {type(err).__name__}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise ValidatorError("TypeSafe answered 200 without JSON", 200) from None
                error = ValidatorError(
                    f"TypeSafe answered {resp.status_code}: {resp.text[:300]}", resp.status_code
                )
                if resp.status_code not in RETRY_STATUSES:
                    raise error  # 400/401/413/415/422: the request or the key is wrong
            if attempt < s.jev_max_retries:
                self.sleep(retry_delay(resp, attempt + 1, self.rand))
        raise error

    def validate(self, image_bgr: np.ndarray, candidates: list[Detection]) -> list[Verdict]:
        """One verdict per candidate, strongest first. Candidates beyond JEV_MAX_CANDIDATES are not
        sent and do not pass. Raises ValidatorError when Jev cannot answer."""
        s = self.settings
        ranked = sorted(candidates, key=lambda d: -d.conf)
        asked, skipped = ranked[: s.jev_max_candidates], ranked[s.jev_max_candidates :]
        verdicts: list[Verdict] = []
        if asked:
            body, parts = self.build_request(image_bgr, asked)
            answer = self.ask(body, parts)
            answers = answer.get("answers") or {}
            for i, d in enumerate(asked):
                a = answers.get(f"candidate_{i}") or {}
                noul = a.get("noul")
                if a.get("type") != "noul" or not isinstance(noul, int | float):
                    raise ValidatorError(f"TypeSafe answer for candidate_{i} is malformed: {a!r}")
                noul = float(noul)
                verdicts.append(Verdict(d, round(noul, 4), noul >= s.jev_min_noul))
            log.info("jev validation", extra={"fields": {
                "model": answer.get("model"), "candidates": len(asked),
                "passed": sum(v.passed for v in verdicts), "usage": answer.get("usage")}})  # fmt: skip
        verdicts += [Verdict(d, None, False) for d in skipped]
        return verdicts
