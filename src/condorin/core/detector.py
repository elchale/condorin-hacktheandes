"""Detector interface, the Ultralytics YOLO implementation (sliced inference) and a fake for dev/tests.

The rest of the service only depends on the `Detector` protocol, so the model can be swapped (another
detector, or a commercially licensed one) without touching the pipeline.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from condorin.core.model_card import ModelCard
from condorin.core.tiling import tile_offsets

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    cls: str
    conf: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in full-image pixels


class Detector(Protocol):
    card: ModelCard
    device: str

    def detect(self, image_bgr: np.ndarray) -> list[Detection]: ...


# (image, [(x0, y0, x1, y1), ...]) -> boolean keep mask, one entry per tile
TileFilter = Callable[[np.ndarray, list[tuple[int, int, int, int]]], np.ndarray]


def np_nms(boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray, thr: float) -> list[int]:
    """Class-aware greedy NMS (numpy only). Returns kept indices."""
    keep: list[int] = []
    for c in np.unique(classes):
        idx = np.where(classes == c)[0]
        idx = idx[np.argsort(-scores[idx])]
        while len(idx):
            i = idx[0]
            keep.append(int(i))
            if len(idx) == 1:
                break
            rest = idx[1:]
            xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
            yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
            xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
            yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            a_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            a_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
            idx = rest[inter / np.maximum(a_i + a_r - inter, 1e-9) <= thr]
    return keep


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:  # pragma: no cover
        return "cpu"


class ModelCardMismatch(ValueError):
    """The weights and model_card.json disagree; serving them would mislabel detections."""


def check_class_names(model_names: dict[int, str] | list[str], card: ModelCard) -> None:
    """`card.classes` must list the model's class names in index order.

    Detections are labelled by index into `card.classes`, so a reordered or shorter list would
    silently report the wrong class (or crash on the first box)."""
    names = (
        [model_names[i] for i in sorted(model_names)]
        if isinstance(model_names, dict)
        else list(model_names)
    )
    if names != list(card.classes):
        raise ModelCardMismatch(
            f"model_card.json classes {card.classes} do not match the weights' class names "
            f"{names} (same names, same order required)"
        )


class YoloDetector:
    """Ultralytics YOLO with native-resolution sliced inference, exactly as evaluated."""

    def __init__(
        self,
        card: ModelCard,
        model_dir: str | Path,
        device: str = "auto",
        batch: int = 8,
        torch_threads: int | None = None,
        tile_filter: TileFilter | None = None,
    ) -> None:
        from ultralytics import YOLO  # lazy: heavy import, and AGPL code stays behind this class

        if torch_threads:
            import torch

            torch.set_num_threads(torch_threads)
        self.card = card
        self.device = resolve_device(device)
        self.batch = batch
        self.tile_filter = tile_filter
        weights = Path(model_dir) / card.weights
        if not weights.is_file():
            raise FileNotFoundError(f"model weights not found: {weights}")
        self.model = YOLO(str(weights), task="detect")
        check_class_names(self.model.names, card)

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        inf = self.card.inference
        t, ov = inf.tile, inf.overlap
        h, w = image_bgr.shape[:2]
        offs = tile_offsets(h, w, t, ov)
        if self.tile_filter is not None:
            rects = [(x0, y0, min(x0 + t, w), min(y0 + t, h)) for x0, y0 in offs]
            keep = self.tile_filter(image_bgr, rects)
            offs = [o for o, k in zip(offs, keep, strict=True) if k]
        crops = [image_bgr[y0 : y0 + t, x0 : x0 + t] for x0, y0 in offs]

        b_all, s_all, c_all = [], [], []
        for i in range(0, len(crops), self.batch):
            res = self.model.predict(
                crops[i : i + self.batch],
                imgsz=t,
                conf=inf.conf_floor,
                iou=inf.predict_iou,
                device=self.device,
                verbose=False,
            )
            for r, (x0, y0) in zip(res, offs[i : i + self.batch], strict=True):
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                b = r.boxes.xyxy.cpu().numpy().astype(float)
                b[:, [0, 2]] += x0
                b[:, [1, 3]] += y0
                b_all.append(b)
                s_all.append(r.boxes.conf.cpu().numpy())
                c_all.append(r.boxes.cls.cpu().numpy().astype(int))
        if not b_all:
            return []
        boxes, scores, classes = map(np.concatenate, (b_all, s_all, c_all))
        keep = np_nms(boxes, scores, classes, inf.nms_iou)
        return [
            Detection(self.card.classes[classes[i]], float(scores[i]), tuple(map(float, boxes[i])))
            for i in keep
        ]


class FakeDetector:
    """Deterministic stand-in (FAKE_MODEL=1): 0-2 plausible vessel boxes seeded by the image content."""

    def __init__(self, card: ModelCard) -> None:
        self.card = card
        self.device = "fake"
        self.calls = 0  # lets tests verify that cached results skip compute

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        self.calls += 1
        digest = hashlib.sha1(np.ascontiguousarray(image_bgr).tobytes()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        h, w = image_bgr.shape[:2]
        out: list[Detection] = []
        for _ in range(int(rng.integers(0, 3))):
            length = float(rng.uniform(25, 60))
            width = float(rng.uniform(8, 20))
            bw, bh = (length, width) if rng.random() < 0.5 else (width, length)
            bw, bh = min(bw, w), min(bh, h)
            x1 = float(rng.uniform(0, max(w - bw, 0)))
            y1 = float(rng.uniform(0, max(h - bh, 0)))
            cls = self.card.classes[int(rng.integers(0, len(self.card.classes)))]
            conf = float(round(rng.uniform(0.05, 0.95), 4))
            out.append(Detection(cls, conf, (x1, y1, x1 + bw, y1 + bh)))
        return out


def build_detector(
    settings, card: ModelCard
) -> Detector:  # settings: condorin.job.config.JobSettings
    if settings.fake_model:
        return FakeDetector(card)
    tile_filter = None
    if settings.gate_enabled:
        from condorin.core.gating import tiles_with_water

        tile_filter = tiles_with_water
    return YoloDetector(
        card,
        settings.model_dir,
        device=settings.device,
        batch=settings.infer_batch,
        torch_threads=settings.torch_threads,
        tile_filter=tile_filter,
    )
