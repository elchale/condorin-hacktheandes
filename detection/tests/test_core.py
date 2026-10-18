from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import encode, make_image
from pydantic import ValidationError

from condorin.core.decision import decide, presence_score
from condorin.core.detector import Detection, FakeDetector, np_nms
from condorin.core.gating import tiles_with_water, water_mask
from condorin.core.model_card import ModelCard, Thresholds, load_model_card
from condorin.core.qc import QCReason, lost_rows, run_qc, sniff_format
from condorin.core.tiling import iter_tiles, tile_offsets, tile_starts

# --- tiling -------------------------------------------------------------------------------------


@pytest.mark.parametrize("length", [640, 641, 1000, 1280, 2560, 2561, 3001])
def test_tile_starts_covers_whole_length(length):
    starts = tile_starts(length, 640, 128)
    covered = np.zeros(length, bool)
    for s in starts:
        covered[s : s + 640] = True
    assert covered.all()
    assert starts[0] == 0
    assert starts[-1] + 640 == length  # last tile flush with the edge
    assert starts == sorted(set(starts))


def test_tile_starts_smaller_than_tile():
    assert tile_starts(300, 640, 128) == [0]
    tiles = list(iter_tiles(np.zeros((300, 500, 3), np.uint8), 640, 128))
    assert len(tiles) == 1 and tiles[0][2].shape == (300, 500, 3)


def test_tile_starts_step():
    assert tile_starts(1280, 640, 128) == [0, 512, 640]
    assert len(tile_offsets(1280, 1280, 640, 128)) == 9


# --- NMS ----------------------------------------------------------------------------------------


def test_np_nms_class_aware():
    boxes = np.array(
        [[0, 0, 10, 10], [1, 1, 11, 11], [0, 0, 10, 10], [50, 50, 60, 60]], dtype=float
    )
    scores = np.array([0.9, 0.8, 0.7, 0.6])
    classes = np.array([0, 0, 1, 0])
    keep = np_nms(boxes, scores, classes, 0.5)
    assert sorted(keep) == [0, 2, 3]  # box 1 suppressed by 0; box 2 is another class


def test_np_nms_keeps_low_overlap():
    boxes = np.array([[0, 0, 10, 10], [6, 0, 16, 10]], dtype=float)  # IoU = 4/16 = 0.25
    keep = np_nms(boxes, np.array([0.9, 0.8]), np.array([0, 0]), 0.5)
    assert sorted(keep) == [0, 1]


# --- decision -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "clear"),
        (0.2499, "clear"),
        (0.25, "needs_review"),
        (0.6199, "needs_review"),
        (0.62, "detected"),
        (1.0, "detected"),
    ],
)
def test_decide_boundaries(score, expected):
    assert decide(score, Thresholds(detect=0.62, review_low=0.25)) == expected


def test_presence_score_positive_class_only():
    dets = [
        Detection("other_vessel", 0.99, (0, 0, 1, 1)),
        Detection("mining_vessel", 0.4, (0, 0, 1, 1)),
    ]
    assert presence_score(dets, "mining_vessel") == 0.4
    assert presence_score([], "mining_vessel") == 0.0


# --- model card ---------------------------------------------------------------------------------

CARD = {
    "name": "dredge-detector", "version": "2026-10-r1", "weights": "best.pt",
    "classes": ["mining_vessel", "other_vessel"], "positive_class": "mining_vessel",
    "inference": {"tile": 640, "overlap": 128, "conf_floor": 0.05, "nms_iou": 0.5},
    "thresholds": {"detect": 0.62, "review_low": 0.25},
    "qc": {"expected_gsd_m": None, "gsd_tolerance": 0.25, "min_side_px": 640,
           "max_nodata_fraction": 0.5, "max_truncated_lost_fraction": 0.2},
    "training": {"dataset": "x", "date": "2026-10-01"}, "metrics": {"val": {}, "test": {}},
}  # fmt: skip


def test_model_card_loads(tmp_path):
    (tmp_path / "model_card.json").write_text(json.dumps(CARD))
    card = load_model_card(tmp_path)
    assert card.version == "2026-10-r1" and card.thresholds.detect == 0.62
    assert card.inference.tile == 640


def test_model_card_rejects_unknown_positive_class():
    with pytest.raises(ValidationError, match="positive_class"):
        ModelCard.model_validate({**CARD, "positive_class": "dredge"})


def test_model_card_rejects_inverted_thresholds():
    with pytest.raises(ValidationError, match="review_low"):
        ModelCard.model_validate({**CARD, "thresholds": {"detect": 0.3, "review_low": 0.5}})


# --- QC -----------------------------------------------------------------------------------------


def test_qc_ok(card, jpeg_bytes):
    r = run_qc(jpeg_bytes, card.qc)
    assert r.passed and r.reasons == []
    assert r.image_bgr.shape == (1280, 1280, 3)
    assert r.checks["format"] == "jpeg" and r.checks["truncated"] is False


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_qc_truncated_recoverable(card, fmt):
    raw = encode(make_image(seed=3), fmt)
    r = run_qc(raw[: int(len(raw) * 0.92)], card.qc)
    assert r.passed, r.reasons
    assert r.checks["truncated"] is True
    frac = r.checks["truncated_lost_fraction"]
    assert 0.0 < frac <= card.qc.max_truncated_lost_fraction
    assert r.height == 1280  # full height kept for geo mapping
    assert r.image_bgr.shape[0] < 1280  # only surviving pixels are processed


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_qc_truncated_too_much(card, fmt):
    raw = encode(make_image(seed=4), fmt)
    r = run_qc(raw[: len(raw) // 2], card.qc)
    assert not r.passed and r.reasons == [QCReason.TRUNCATED_TOO_MUCH]
    assert r.checks["truncated_lost_fraction"] > 0.2


def test_lost_rows():
    rgb = np.random.default_rng(0).integers(0, 255, (100, 50, 3)).astype(np.uint8)
    rgb[90:] = 128
    assert lost_rows(rgb) == 10


def test_qc_unsupported_and_unreadable(card):
    assert run_qc(b"GIF89a....", card.qc).reasons == [QCReason.UNSUPPORTED_FORMAT]
    assert run_qc(b"\xff\xd8\xff" + b"\x00" * 50, card.qc).reasons == [QCReason.UNREADABLE]
    assert sniff_format(encode(make_image(64, 64), "PNG")) == "png"


def test_qc_too_small_and_nodata(card):
    assert run_qc(encode(make_image(500, 800)), card.qc).reasons == [QCReason.TOO_SMALL]
    black = np.zeros((800, 800, 3), np.uint8)
    assert QCReason.TOO_MUCH_NODATA in run_qc(encode(black, "PNG"), card.qc).reasons


def test_qc_gsd(card, jpeg_bytes):
    r = run_qc(jpeg_bytes, card.qc, gsd_m=0.5)
    assert r.passed and r.checks["gsd_checked"] is False  # card has no expected_gsd_m
    spec = card.qc.model_copy(update={"expected_gsd_m": 0.5})
    assert run_qc(jpeg_bytes, spec, gsd_m=0.55).passed
    r = run_qc(jpeg_bytes, spec, gsd_m=1.0)
    assert r.reasons == [QCReason.GSD_MISMATCH] and r.checks["gsd_checked"] is True


# --- fake detector + gate -----------------------------------------------------------------------


def test_fake_detector_deterministic(card):
    det = FakeDetector(card)
    outs = [det.detect(make_image(1280, 1280, seed=s)[..., ::-1]) for s in range(20)]
    again = [det.detect(make_image(1280, 1280, seed=s)[..., ::-1]) for s in range(20)]
    assert outs == again and det.calls == 40
    flat = [d for o in outs for d in o]
    assert flat, "expected some boxes over 20 images"
    for d in flat:
        assert d.cls in card.classes and 0.05 <= d.conf <= 0.95
        x1, y1, x2, y2 = d.box
        assert 0 <= x1 < x2 <= 1280 and 0 <= y1 < y2 <= 1280
        assert 25 <= max(x2 - x1, y2 - y1) <= 60
    assert all(len(o) <= 2 for o in outs)


def test_gate_keeps_river_tiles():
    rgb = np.zeros((1280, 1280, 3), np.uint8)
    rgb[...] = (30, 90, 30)  # forest
    rgb[200:500] = (175, 140, 95)  # smooth muddy river band in the first tile row
    bgr = rgb[..., ::-1].copy()
    assert water_mask(bgr)[300].all()
    tiles = [(0, 0, 640, 640), (0, 640, 640, 1280)]
    assert tiles_with_water(bgr, tiles).tolist() == [True, False]
