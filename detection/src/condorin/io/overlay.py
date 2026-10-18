"""Overlay rendering: boxes on the image (positive class red, others orange), downscaled JPEG."""

from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np

from condorin.core.detector import Detection

MAX_SIDE = 1600
RED = (0, 0, 255)  # BGR
ORANGE = (0, 165, 255)


def render_overlay(
    image_bgr: np.ndarray,
    detections: Iterable[Detection],
    positive_class: str,
    max_side: int = MAX_SIDE,
    quality: int = 85,
) -> bytes:
    h, w = image_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    img = image_bgr
    if scale < 1.0:
        img = cv2.resize(
            image_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA
        )
    else:
        img = image_bgr.copy()
    for d in detections:
        color = RED if d.cls == positive_class else ORANGE
        x1, y1, x2, y2 = (round(v * scale) for v in d.box)
        pad = 4  # vessels are small: pad the box so it stays visible after downscaling
        cv2.rectangle(img, (x1 - pad, y1 - pad), (x2 + pad, y2 + pad), color, 2)
        label = f"{d.cls} {d.conf:.2f}"
        cv2.putText(img, label, (x1 - pad, max(y1 - pad - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    color, 1, cv2.LINE_AA)  # fmt: skip
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:  # pragma: no cover
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()
