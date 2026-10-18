"""Image-level presence score and the three-way decision."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from condorin.core.detector import Detection
from condorin.core.model_card import Thresholds

Decision = Literal["detected", "needs_review", "clear"]


def presence_score(detections: Iterable[Detection], positive_class: str) -> float:
    """Max confidence of the positive class over the whole image (0.0 if none)."""
    return max((d.conf for d in detections if d.cls == positive_class), default=0.0)


def decide(score: float, thr: Thresholds) -> Decision:
    return (
        "detected"
        if score >= thr.detect
        else "needs_review"
        if score >= thr.review_low
        else "clear"
    )
