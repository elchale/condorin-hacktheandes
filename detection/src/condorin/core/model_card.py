"""`model_card.json`: the pinned model's identity, inference settings, thresholds and QC limits."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_CARD_FILE = "model_card.json"


class InferenceSpec(BaseModel):
    tile: int = Field(640, gt=0)
    overlap: int = Field(128, ge=0)
    conf_floor: float = Field(0.05, ge=0.0, le=1.0)
    nms_iou: float = Field(0.5, gt=0.0, le=1.0)
    predict_iou: float = Field(0.6, gt=0.0, le=1.0)  # per-tile NMS inside the YOLO predict call

    @model_validator(mode="after")
    def _overlap_lt_tile(self) -> InferenceSpec:
        if self.overlap >= self.tile:
            raise ValueError("inference.overlap must be smaller than inference.tile")
        return self


class Thresholds(BaseModel):
    detect: float = Field(ge=0.0, le=1.0)
    review_low: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if self.review_low > self.detect:
            raise ValueError("thresholds.review_low must be <= thresholds.detect")
        return self


class QCSpec(BaseModel):
    expected_gsd_m: float | None = None
    gsd_tolerance: float = 0.25
    min_side_px: int = 640
    max_nodata_fraction: float = 0.5
    max_truncated_lost_fraction: float = 0.2


class ModelCard(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    name: str
    version: str
    weights: str = "best.pt"
    classes: list[str] = Field(min_length=1)
    positive_class: str
    inference: InferenceSpec = InferenceSpec()
    thresholds: Thresholds
    qc: QCSpec = QCSpec()
    training: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _positive_in_classes(self) -> ModelCard:
        if self.positive_class not in self.classes:
            raise ValueError(
                f"positive_class {self.positive_class!r} is not in classes {self.classes}"
            )
        return self

    @classmethod
    def placeholder(cls) -> ModelCard:
        """Card used with FAKE_MODEL=1 when no real card is present. Thresholds are placeholders."""
        return cls(
            name="dredge-detector",
            version="fake-0",
            weights="",
            classes=["mining_vessel", "other_vessel"],
            positive_class="mining_vessel",
            thresholds=Thresholds(detect=0.62, review_low=0.25),
            training={"dataset": "none", "note": "placeholder card for FAKE_MODEL=1"},
        )


def load_model_card(model_dir: str | Path) -> ModelCard:
    path = Path(model_dir) / MODEL_CARD_FILE
    return ModelCard.model_validate(json.loads(path.read_text()))
