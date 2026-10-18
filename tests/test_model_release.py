"""Checks that stop a mismatched or broken model from being deployed."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from condorin.core.detector import ModelCardMismatch, YoloDetector, check_class_names
from condorin.core.model_card import ModelCard
from condorin.job.runner import main, warn_runtime_drift

CARD = {
    "name": "dredge-detector", "version": "2026-10-r1", "weights": "best.pt",
    "classes": ["mining_vessel", "other_vessel"], "positive_class": "mining_vessel",
    "thresholds": {"detect": 0.62, "review_low": 0.25},
}  # fmt: skip


def model_dir(tmp_path: Path, **card_over) -> Path:
    d = tmp_path / "model"
    d.mkdir(exist_ok=True)
    (d / "model_card.json").write_text(json.dumps({**CARD, **card_over}))
    (d / "best.pt").write_bytes(b"not really weights")
    return d


@pytest.fixture
def stub_yolo(monkeypatch):
    """A fake `ultralytics` module whose YOLO weights carry the given class names."""
    state = {"names": {0: "mining_vessel", 1: "other_vessel"}}

    class YOLO:
        def __init__(self, path, task=None):
            self.names = state["names"]

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=YOLO))
    return state


def load_check_model():
    path = Path(__file__).parents[1] / "scripts" / "check_model.py"
    spec = importlib.util.spec_from_file_location("check_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- class names --------------------------------------------------------------------------------


def test_check_class_names():
    card = ModelCard.model_validate(CARD)
    check_class_names({0: "mining_vessel", 1: "other_vessel"}, card)
    check_class_names({1: "other_vessel", 0: "mining_vessel"}, card)  # dict order irrelevant
    check_class_names(["mining_vessel", "other_vessel"], card)
    with pytest.raises(ModelCardMismatch, match="same order"):
        check_class_names({0: "other_vessel", 1: "mining_vessel"}, card)  # swapped
    with pytest.raises(ModelCardMismatch):
        check_class_names({0: "mining_vessel"}, card)  # fewer classes
    with pytest.raises(ModelCardMismatch):
        check_class_names({0: "mining_vessel", 1: "other_vessel", 2: "log"}, card)


def test_yolo_detector_refuses_mismatched_weights(tmp_path, stub_yolo):
    d = model_dir(tmp_path)
    card = ModelCard.model_validate(CARD)
    assert YoloDetector(card, d, device="cpu").card is card
    stub_yolo["names"] = {0: "other_vessel", 1: "mining_vessel"}
    with pytest.raises(ModelCardMismatch):
        YoloDetector(card, d, device="cpu")


def test_job_exits_2_on_mismatched_weights(tmp_path, monkeypatch, stub_yolo):
    stub_yolo["names"] = {0: "boat", 1: "mining_vessel"}
    monkeypatch.setenv("MODEL_DIR", str(model_dir(tmp_path)))
    monkeypatch.setenv("INPUT_BUCKET", str(tmp_path / "bucket"))
    monkeypatch.setenv("PREFIX", "yaguas/")
    monkeypatch.setenv("DEVICE", "cpu")
    monkeypatch.setenv("FAKE_MODEL", "0")
    monkeypatch.setenv("WEBHOOK_MODE", "log")
    assert main() == 2


# --- runtime versions ---------------------------------------------------------------------------


def test_warn_runtime_drift(monkeypatch, caplog):
    installed = {"ultralytics": "8.4.182", "torch": "2.14.1+cpu"}
    monkeypatch.setattr(importlib.metadata, "version", lambda pkg: installed[pkg])
    same = ModelCard.model_validate(
        {**CARD, "training": {"ultralytics": "8.4.182", "torch": "2.14.1"}}
    )
    assert warn_runtime_drift(same) == []
    old = ModelCard.model_validate({**CARD, "training": {"ultralytics": "8.3.0"}})
    assert warn_runtime_drift(old) == ["ultralytics 8.4.182 (model trained with 8.3.0)"]
    assert "differs from training" in caplog.text
    assert warn_runtime_drift(ModelCard.model_validate(CARD)) == []  # nothing recorded


# --- scripts/check_model.py ---------------------------------------------------------------------


def test_check_model_ok(tmp_path, capsys):
    cm = load_check_model()
    assert cm.check(model_dir(tmp_path), "dredge-detector", load=False) == "2026-10-r1"


@pytest.mark.parametrize(
    "over,message",
    [
        ({"name": "condorin-yolo"}, "backend expects"),
        ({"weights": "missing.pt"}, "not found"),
        ({"weights": "model_card.json"}, "unsupported weights format"),
        ({"thresholds": {"detect": 0.2, "review_low": 0.5}}, "review_low"),
        ({"positive_class": "dredge"}, "positive_class"),
    ],
)
def test_check_model_rejects(tmp_path, over, message):
    cm = load_check_model()
    with pytest.raises(SystemExit, match=message):
        cm.check(model_dir(tmp_path, **over), "dredge-detector", load=False)


def test_check_model_empty_weights_and_no_card(tmp_path):
    cm = load_check_model()
    d = model_dir(tmp_path)
    (d / "best.pt").write_bytes(b"")
    with pytest.raises(SystemExit, match="empty"):
        cm.check(d, "dredge-detector", load=False)
    with pytest.raises(SystemExit, match="not found"):
        cm.check(tmp_path / "nothing", "dredge-detector", load=False)


def test_check_model_load_compares_classes(tmp_path, stub_yolo):
    cm = load_check_model()
    d = model_dir(tmp_path)
    assert cm.check(d, "dredge-detector", load=True) == "2026-10-r1"
    stub_yolo["names"] = {0: "other_vessel", 1: "mining_vessel"}
    with pytest.raises(SystemExit, match="do not match"):
        cm.check(d, "dredge-detector", load=True)
