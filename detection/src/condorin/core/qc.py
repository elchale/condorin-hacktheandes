"""Image quality control: decode (strict, then tolerant for truncated files), size, nodata, GSD.

Inputs are JPG/PNG only (detected by magic bytes). They carry no reliable geo metadata, so the GSD check
only runs when the job supplies `options.gsd_m` and the model card has `expected_gsd_m`.
Cloud cover is a documented extension point (not implemented): add a check here returning a new reason.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile

from condorin.core.model_card import QCSpec

SAFETY_ROWS = 16  # extra rows cropped above an estimated truncation boundary
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_decode_lock = threading.Lock()  # ImageFile.LOAD_TRUNCATED_IMAGES is a process-wide flag


class QCReason(StrEnum):
    UNREADABLE = "unreadable"
    TRUNCATED_TOO_MUCH = "truncated_too_much"
    TOO_SMALL = "too_small"
    TOO_MUCH_NODATA = "too_much_nodata"
    GSD_MISMATCH = "gsd_mismatch"
    UNSUPPORTED_FORMAT = "unsupported_format"


@dataclass
class QCResult:
    passed: bool
    reasons: list[QCReason] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    image_bgr: np.ndarray | None = None  # surviving pixels only (truncated band cropped)
    width: int = 0
    height: int = 0  # FULL decoded height (keeps the blank band): use it for geo mapping

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reasons": [str(r) for r in self.reasons],
            "truncated_lost_fraction": self.checks.get("truncated_lost_fraction", 0.0),
            "gsd_checked": self.checks.get("gsd_checked", False),
            "checks": self.checks,
        }


def sniff_format(raw: bytes) -> str | None:
    if raw.startswith(_JPEG_MAGIC):
        return "jpeg"
    if raw.startswith(_PNG_MAGIC):
        return "png"
    return None


def lost_rows(rgb: np.ndarray) -> int:
    """Count perfectly flat bottom rows (decoder fill after truncation). An estimate: a real nodata
    band looks identical."""
    a = rgb.astype(np.int16)
    flat = (a.max(axis=1) - a.min(axis=1)).max(axis=1) <= 2
    n = 0
    for v in flat[::-1]:
        if not v:
            break
        n += 1
    return n


def _decode(raw: bytes, tolerant: bool) -> np.ndarray:
    with _decode_lock:
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = tolerant
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
                rgb = im.convert("RGB")
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous
    return np.asarray(rgb)


def nodata_fraction(rgb: np.ndarray) -> float:
    """Share of pure-black or pure-white pixels (typical fill values outside the scene footprint)."""
    if rgb.size == 0:
        return 1.0
    black = (rgb == 0).all(axis=2)
    white = (rgb == 255).all(axis=2)
    return float((black | white).mean())


def run_qc(raw: bytes | str | Path, spec: QCSpec, gsd_m: float | None = None) -> QCResult:
    if not isinstance(raw, bytes):
        raw = Path(raw).read_bytes()
    checks: dict = {"truncated": False, "truncated_lost_fraction": 0.0, "gsd_checked": False}

    fmt = sniff_format(raw)
    checks["format"] = fmt
    if fmt is None:
        return QCResult(False, [QCReason.UNSUPPORTED_FORMAT], checks)

    try:
        rgb = _decode(raw, tolerant=False)
    except Exception as strict_err:  # noqa: BLE001 - PIL raises OSError/SyntaxError/ValueError...
        checks["strict_decode_error"] = str(strict_err)[:200]
        try:
            rgb = _decode(raw, tolerant=True)
        except Exception as err:  # noqa: BLE001
            checks["decode_error"] = str(err)[:200]
            return QCResult(False, [QCReason.UNREADABLE], checks)
        checks["truncated"] = True

    full_h, w = rgb.shape[:2]
    checks["width"], checks["height"] = w, full_h
    valid = rgb
    if checks["truncated"]:
        n = lost_rows(rgb)
        frac = n / full_h if full_h else 1.0
        checks["truncated_lost_fraction"] = round(frac, 4)
        checks["truncated_lost_rows_estimate"] = n
        if frac > spec.max_truncated_lost_fraction:
            return QCResult(False, [QCReason.TRUNCATED_TOO_MUCH], checks, None, w, full_h)
        keep = full_h - n - SAFETY_ROWS if n else full_h
        valid = rgb[: max(keep, 0)]
        checks["valid_height"] = int(valid.shape[0])

    reasons: list[QCReason] = []
    if min(w, valid.shape[0]) < spec.min_side_px:
        reasons.append(QCReason.TOO_SMALL)
    nd = nodata_fraction(valid)
    checks["nodata_fraction"] = round(nd, 4)
    if nd > spec.max_nodata_fraction:
        reasons.append(QCReason.TOO_MUCH_NODATA)
    if gsd_m is not None and spec.expected_gsd_m:
        checks["gsd_checked"] = True
        checks["gsd_m"] = gsd_m
        rel = abs(gsd_m - spec.expected_gsd_m) / spec.expected_gsd_m
        if rel > spec.gsd_tolerance:
            reasons.append(QCReason.GSD_MISMATCH)

    if reasons:
        return QCResult(False, reasons, checks, None, w, full_h)
    bgr = np.ascontiguousarray(valid[..., ::-1])
    return QCResult(True, [], checks, bgr, w, full_h)
