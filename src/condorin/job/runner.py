"""Cloud Run Job: process every image under `gs://<INPUT_BUCKET>/<PREFIX>` and report each one.

Per image: read its generation and metadata → read that exact version → QC (with the scene's GSD
when its metadata has `gsd_m`) → detect → keep the positive class above `min_confidence` → with
JEV_ENABLED, keep detections at or above `jev_trigger_confidence` only if TypeSafe Jev confirms them
(condorin.job.validator) → upload one crop per box → POST to the backend.
Every readable image is reported, also with `"detections": []` (the backend stores it as "reviewed,
nothing found"). An image is *not* reported, and counts as failed, when posting it would be wrong:
QC rejected it, metadata the backend requires is missing, or it has findings but no bounds to put
them on the map (an empty report would hide them).

Work is split across the Job's tasks by `CLOUD_RUN_TASK_INDEX` / `CLOUD_RUN_TASK_COUNT`. A task
stops starting images when its time budget would be exceeded, and writes a JSON report of every image
it did not report (`<bucket>/reports/<execution>/task-NNN.json`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import cv2
import numpy as np

from condorin.core.detector import Detector, ModelCardMismatch
from condorin.core.meta import box_to_webhook, idempotency_key, resolve_image_meta
from condorin.core.model_card import ModelCard
from condorin.core.qc import run_qc
from condorin.io import storage
from condorin.job.config import JobSettings
from condorin.job.report import DeliveryError, Reporter
from condorin.job.validator import JevValidator, ValidatorError

log = logging.getLogger(__name__)

STARTED = time.monotonic()  # process start: the task timeout runs from container start
MAX_DETECTIONS = 500  # backend limit per image
_SLUG = re.compile(r"^[-a-zA-Z0-9_]+$")


class SkipImage(Exception):
    """The image cannot be reported correctly; `reason` is a short machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class Summary:
    listed: int = 0
    processed: int = 0  # reported to the backend
    with_findings: int = 0
    without_findings: int = 0
    duplicates: int = 0
    alerted: int = 0
    failed: int = 0
    gsd_unchecked: int = 0  # the card expects a GSD but the scene's metadata has no gsd_m
    jev_confirmed: int = 0  # detections Jev confirmed (reported)
    jev_rejected: int = 0  # detections Jev did not confirm (not reported; listed in the report)
    jev_rejections: list[dict] = field(default_factory=list)
    failures: Counter = field(default_factory=Counter)
    not_reported: list[dict] = field(default_factory=list)  # {"object", "reason", "detail"}

    def fail(self, obj: str, reason: str, detail: str = "") -> None:
        self.failed += 1
        self.failures[reason] += 1
        self.not_reported.append({"object": obj, "reason": reason, "detail": detail[:500]})

    def as_fields(self) -> dict:
        lists = ("failures", "not_reported", "jev_rejections")
        d = {k: v for k, v in self.__dict__.items() if k not in lists}
        return {**d, "failures_by_reason": dict(self.failures)}


def shard(items: list[str], index: int, count: int) -> list[str]:
    return items[index::count] if count > 1 else items


def bucket_root(settings: JobSettings) -> str:
    """`gs://<bucket>`, or a local directory standing in for the bucket (dev and tests)."""
    b = settings.input_bucket.rstrip("/")
    return b if "://" in b or b.startswith(("/", ".")) else f"gs://{b}"


def list_images(settings: JobSettings, prefix: str) -> list[str]:
    """Object names (relative to the bucket) under `prefix`, without crops and non-images."""
    root = bucket_root(settings)
    local = storage.parse_uri(root).path
    if local is None:
        names = [
            u[len(root) + 1 :] for u in storage.list_uris(f"{root}/{prefix}")
        ]  # keeps a trailing /
    else:  # a local dir: list it all and match the prefix like GCS does
        names = [str(PurePosixPath(u).relative_to(local)) for u in storage.list_uris(root)]
        names = [n for n in names if n.startswith(prefix)]
    crops = settings.crops_prefix.strip("/") + "/"
    return [
        n for n in names
        if not n.startswith(crops) and n.lower().endswith(settings.image_suffixes)
    ]  # fmt: skip


def gsd_from_metadata(metadata: dict) -> float | None:
    """Ground sample distance (m/px) from the object's custom metadata `gsd_m`, if present."""
    raw = (metadata or {}).get("gsd_m")
    if raw in (None, ""):
        return None
    try:
        gsd = float(raw)
    except (TypeError, ValueError):
        raise SkipImage("bad_gsd_m", f"custom metadata gsd_m={raw!r} is not a number") from None
    if not 0 < gsd < 1000:
        raise SkipImage("bad_gsd_m", f"custom metadata gsd_m={raw!r} is out of range")
    return gsd


def crop_png(image_bgr: np.ndarray, xyxy: tuple[float, ...], pad: int, min_side: int) -> bytes:
    """The box plus `pad` px on each side, at least `min_side` px wide and tall, clamped to the image."""
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = xyxy
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half_w = max((x2 - x1) / 2 + pad, min_side / 2)
    half_h = max((y2 - y1) / 2 + pad, min_side / 2)
    left, top = max(int(cx - half_w), 0), max(int(cy - half_h), 0)
    right, bottom = min(int(np.ceil(cx + half_w)), w), min(int(np.ceil(cy + half_h)), h)
    ok, buf = cv2.imencode(".png", image_bgr[top:bottom, left:right])
    if not ok:  # pragma: no cover
        raise SkipImage("crop_encode_failed")
    return buf.tobytes()


class Runner:
    def __init__(
        self,
        settings: JobSettings,
        card: ModelCard,
        detector: Detector,
        reporter: Reporter,
        validator: JevValidator | None = None,
    ) -> None:
        self.settings = settings
        self.card = card
        self.detector = detector
        self.reporter = reporter
        self.validator = validator
        self.gsd_unchecked = 0
        self.jev_confirmed = 0
        self.jev_rejections: list[dict] = []

    @property
    def min_confidence(self) -> float:
        s = self.settings.min_confidence
        return self.card.thresholds.review_low if s is None else s

    def crop_object(self, obj: str, generation: str, i: int) -> str:
        """`crops/<object without extension>/<generation>/<model version>/<i>.png`"""
        stem = PurePosixPath(obj).with_suffix("")
        return f"{self.settings.crops_prefix.strip('/')}/{stem}/{generation}/{self.card.version}/{i:03d}.png"

    def run(self, objects: list[str], deadline: float | None = None) -> Summary:
        """Process `objects` in order. With `deadline` (a time.monotonic() value), stop before an
        image that would likely end after it; the rest are recorded as `not_started`."""
        summary = Summary(listed=len(objects))
        root = bucket_root(self.settings)
        slowest = 0.0
        for i, obj in enumerate(objects):
            if deadline is not None and time.monotonic() + slowest > deadline:
                rest = objects[i:]
                for o in rest:
                    summary.fail(o, "not_started", "task time budget reached")
                log.warning("time budget reached, images left for a re-run",
                            extra={"model_version": self.card.version, "fields": {
                                "not_started": len(rest), "first": rest[0]}})  # fmt: skip
                break
            t0 = time.monotonic()
            ctx = {"image_uri": storage.join(root, obj), "model_version": self.card.version}
            try:
                answer, n = self.process(obj)
            except SkipImage as err:
                summary.fail(obj, err.reason, str(err))
                log.warning("image not reported", extra={**ctx, "status": err.reason,
                                                         "error": str(err)})  # fmt: skip
                continue
            except DeliveryError as err:
                summary.fail(obj, f"backend_{err.status or 'unreachable'}", str(err))
                log.error("backend rejected the report", extra={**ctx, "http_status": err.status,
                          "error": str(err), "fields": {"response": err.body}})  # fmt: skip
                continue
            except storage.StorageError as err:
                summary.fail(obj, "storage", f"{type(err).__name__}: {err}")
                log.error("storage error", extra={**ctx, "error": f"{type(err).__name__}: {err}"})
                continue
            finally:
                slowest = max(slowest, time.monotonic() - t0)
                summary.gsd_unchecked = self.gsd_unchecked
                summary.jev_confirmed = self.jev_confirmed
                summary.jev_rejected = len(self.jev_rejections)
                summary.jev_rejections = self.jev_rejections
            summary.processed += 1
            if n:
                summary.with_findings += 1
            else:
                summary.without_findings += 1
            summary.duplicates += bool(answer.get("duplicate"))
            summary.alerted += bool(answer.get("alerted"))
            log.info("image reported", extra={**ctx, "status": "reported", "fields": {
                "detections": n, "backend": answer,
                "elapsed_ms": round((time.monotonic() - t0) * 1000)}})  # fmt: skip
        return summary

    def confirm(self, obj: str, image_bgr: np.ndarray, found: list) -> list:
        """With a validator: drop detections at or above jev_trigger_confidence that Jev does not
        confirm. Weaker ones (which the backend stores but does not alert on) pass unchanged.
        If Jev cannot answer the scene is not reported (fail closed); a re-run retries it."""
        trigger = self.settings.jev_trigger_confidence
        strong = [d for d in found if d.conf >= trigger]
        if self.validator is None or not strong:
            return found
        try:
            verdicts = self.validator.validate(image_bgr, strong)
        except ValidatorError as err:
            raise SkipImage("jev_unavailable", str(err)) from err
        passed = {id(v.detection) for v in verdicts if v.passed}
        for v in verdicts:
            if v.passed:
                self.jev_confirmed += 1
                continue
            self.jev_rejections.append({
                "object": obj, "confidence": round(float(v.detection.conf), 4), "noul": v.noul,
                "box_xyxy": [round(x, 1) for x in v.detection.box],
                "reason": "not_checked" if v.noul is None else "below_min_noul",
            })  # fmt: skip
        kept = [d for d in found if d.conf < trigger or id(d) in passed]
        if len(kept) < len(found):
            log.info("jev rejected detections", extra={"fields": {
                "object": obj, "rejected": len(found) - len(kept), "kept": len(kept)}})  # fmt: skip
        return kept

    def process(self, obj: str) -> tuple[dict, int]:
        """Returns (backend answer, number of detections reported)."""
        root = bucket_root(self.settings)
        uri = storage.join(root, obj)
        bucket = storage.parse_uri(uri).bucket
        info = storage.stat(uri)
        generation = info.generation
        raw = storage.read_bytes(uri, generation)  # exactly the version we report

        meta = resolve_image_meta(bucket, obj, info.metadata, None)
        river = (meta["river"] or "").lower()
        if not _SLUG.match(river):
            raise SkipImage("no_river", f"expected <river>/... in the object path, got {obj!r}")
        if not meta["captured_at"]:
            raise SkipImage("no_captured_at",
                            "set custom metadata captured_at or name it <YYYY-MM-DD>T<HHMM>Z_...")  # fmt: skip
        satellite = meta["satellite"] or self.settings.default_satellite

        gsd_m = gsd_from_metadata(info.metadata)
        if gsd_m is None and self.card.qc.expected_gsd_m:
            self.gsd_unchecked += (
                1  # the model is resolution-sensitive but this scene's GSD is unknown
            )
        qc = run_qc(raw, self.card.qc, gsd_m=gsd_m)
        if not qc.passed:
            raise SkipImage("rejected_qc", ",".join(map(str, qc.reasons)))

        found = sorted(
            (d for d in self.detector.detect(qc.image_bgr)
             if d.cls == self.card.positive_class and d.conf >= self.min_confidence),
            key=lambda d: -d.conf,
        )  # fmt: skip
        if found and not meta["bounds"]:
            raise SkipImage("no_bounds", f"{len(found)} findings but no bounds to place them")
        if len(found) > MAX_DETECTIONS:
            log.warning("too many detections, keeping the strongest",
                        extra={"image_uri": uri, "fields": {"found": len(found)}})  # fmt: skip
            found = found[:MAX_DETECTIONS]
        found = self.confirm(obj, qc.image_bgr, found)

        detections = []
        for i, d in enumerate(found):
            bbox, lat, lon = box_to_webhook(d.box, qc.width, qc.height, meta["bounds"])
            png = crop_png(qc.image_bgr, d.box, self.settings.crop_padding_px,
                           self.settings.crop_min_side_px)  # fmt: skip
            crop_obj = self.crop_object(obj, generation, i)
            crop_gen = storage.write_once(storage.join(root, crop_obj), png, "image/png")
            detections.append({
                "lat": lat, "lon": lon, "confidence": round(float(d.conf), 4),
                "bbox": [max(v, 0) for v in bbox],
                "crop_uri": f"gs://{bucket}/{crop_obj}#{crop_gen}",
            })  # fmt: skip

        payload = {
            "image": {
                "bucket": bucket,
                "object": obj,
                "generation": generation,
                "river": river,
                "satellite": satellite,
                "captured_at": meta["captured_at"],
            },
            "model": {"name": self.card.name, "version": self.card.version},
            "detections": detections,
        }
        return self.reporter.post(payload, idempotency_key(bucket, obj, generation)), len(found)


def write_report(
    settings: JobSettings, card: ModelCard, prefix: str, index: int, count: int, summary: Summary
) -> str | None:
    """Write `<bucket>/<reports_prefix>/<execution>/task-NNN.json` (create-only). Returns its URI."""
    if not settings.reports_prefix.strip("/"):
        return None
    execution = os.environ.get("CLOUD_RUN_EXECUTION") or time.strftime(
        "local-%Y%m%dT%H%M%SZ", time.gmtime()
    )
    uri = storage.join(bucket_root(settings), settings.reports_prefix.strip("/"), execution,
                       f"task-{index:03d}.json")  # fmt: skip
    report = {
        "execution": execution,
        "task_index": index,
        "task_count": count,
        "prefix": prefix,
        "bucket": settings.input_bucket,
        "model": {"name": card.name, "version": card.version},
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": summary.as_fields(),
        "not_reported": summary.not_reported,
        "jev_rejections": summary.jev_rejections,
    }
    data = json.dumps(report, ensure_ascii=False, indent=2).encode()
    try:
        storage.write_once(uri, data, "application/json")
    except storage.StorageError as err:
        log.error("could not write the run report", extra={"error": f"{type(err).__name__}: {err}",
                                                          "fields": {"report": uri}})  # fmt: skip
        return None
    return uri


def warn_runtime_drift(card: ModelCard) -> list[str]:
    """Warn when the installed ultralytics/torch differ from the versions the card was trained with
    (`training.ultralytics`, `training.torch`); scores can shift between versions."""
    from importlib.metadata import PackageNotFoundError, version

    drift = []
    for pkg in ("ultralytics", "torch"):
        want = card.training.get(pkg)
        if not want:
            continue
        try:
            have = version(pkg)
        except PackageNotFoundError:
            continue
        if have.split("+")[0] != str(want).split("+")[0]:
            drift.append(f"{pkg} {have} (model trained with {want})")
    if drift:
        log.warning("model runtime differs from training: " + ", ".join(drift),
                    extra={"model_version": card.version})  # fmt: skip
    return drift


def main() -> int:
    from condorin.core.detector import build_detector
    from condorin.core.model_card import load_model_card
    from condorin.logs import setup_logging

    settings = JobSettings()
    setup_logging(settings.log_level)
    prefix = settings.prefix.strip().lstrip("/")
    if not prefix:
        log.error("PREFIX is empty: refusing to process the whole bucket")
        return 2
    if settings.fake_model and settings.webhook_mode == "post" and not settings.allow_fake_post:
        log.error("FAKE_MODEL=1 with WEBHOOK_MODE=post: refusing to send fake detections")
        return 2

    try:
        card = (
            ModelCard.placeholder() if settings.fake_model else load_model_card(settings.model_dir)
        )
    except FileNotFoundError:
        log.error("no model_card.json in MODEL_DIR (was the model baked into the image?)",
                  extra={"fields": {"model_dir": settings.model_dir}})  # fmt: skip
        return 2
    if not settings.fake_model:
        warn_runtime_drift(card)
    try:
        detector = build_detector(settings, card)
    except (ModelCardMismatch, FileNotFoundError) as err:
        log.error(f"model not usable: {err}", extra={"model_version": card.version})
        return 2

    validator = None
    if settings.jev_enabled:
        try:
            validator = JevValidator(settings)
        except ValueError as err:
            log.error(str(err))
            return 2

    index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    objects = list_images(settings, prefix)
    mine = shard(objects, index, count)[: settings.max_images]
    log.info("starting", extra={"model_version": card.version, "fields": {
        "prefix": prefix, "bucket": settings.input_bucket, "images_total": len(objects),
        "images_this_task": len(mine), "task_index": index, "task_count": count,
        "device": detector.device, "webhook_mode": settings.webhook_mode,
        "jev": settings.jev_model if validator else None}})  # fmt: skip

    # The budget counts from process start, so model loading is included, like the task timeout.
    deadline = STARTED + settings.task_budget_s
    summary = Runner(settings, card, detector, Reporter(settings), validator).run(mine, deadline)
    report = write_report(settings, card, prefix, index, count, summary)
    if summary.gsd_unchecked:
        log.warning(f"{summary.gsd_unchecked} scenes had no gsd_m metadata: GSD check skipped",
                    extra={"model_version": card.version})  # fmt: skip
    log.info(
        f"done: {summary.processed} reported ({summary.with_findings} with findings), "
        f"{summary.failed} failed, of {summary.listed}",
        extra={"model_version": card.version, "fields": {"prefix": prefix, "task_index": index,
                                                          "report": report, **summary.as_fields()}},
    )  # fmt: skip
    # A non-zero exit marks the execution as failed in the console; re-running is safe.
    return 1 if summary.failed else 0
