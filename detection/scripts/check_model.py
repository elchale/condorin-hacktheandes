#!/usr/bin/env python
"""Validate a model folder (model_card.json + weights) before it is baked into the Job image.

    python scripts/check_model.py path/to/model            # card + weights file
    python scripts/check_model.py path/to/model --load     # also load the weights (needs .[ml])

Checks: the card parses (positive_class in classes, review_low <= detect, overlap < tile), the weights
file it names exists and is not empty, the name is what the backend expects, and with --load that the
weights' class names match `classes` in order. Prints the model version on stdout (CI reads it);
problems go to stderr with exit code 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from condorin.core.model_card import MODEL_CARD_FILE, load_model_card

EXPECTED_NAME = "dredge-detector"  # model.name the backend receives


def check(model_dir: Path, expected_name: str, load: bool) -> str:
    card_path = model_dir / MODEL_CARD_FILE
    if not card_path.is_file():
        raise SystemExit(f"error: {card_path} not found")
    try:
        card = load_model_card(model_dir)
    except (ValidationError, ValueError) as err:
        raise SystemExit(f"error: invalid {card_path}:\n{err}") from err

    problems = []
    if card.name != expected_name:
        problems.append(f"name is {card.name!r}, the backend expects {expected_name!r}")
    weights = model_dir / card.weights
    if not card.weights or not weights.is_file():
        problems.append(f"weights file {card.weights!r} (from the card) not found in {model_dir}")
    elif weights.stat().st_size == 0:
        problems.append(f"weights file {weights} is empty")
    elif weights.suffix.lower() not in (".pt", ".onnx"):
        problems.append(f"unsupported weights format {weights.suffix!r} (expected .pt or .onnx)")
    if problems:
        raise SystemExit("error: " + "\n       ".join(problems))

    if load:
        from ultralytics import YOLO

        from condorin.core.detector import ModelCardMismatch, check_class_names

        try:
            check_class_names(YOLO(str(weights), task="detect").names, card)
        except ModelCardMismatch as err:
            raise SystemExit(f"error: {err}") from err

    print(
        f"ok: {card.name} {card.version} classes={card.classes} positive={card.positive_class} "
        f"detect={card.thresholds.detect} review_low={card.thresholds.review_low}",
        file=sys.stderr,
    )
    return card.version


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("--expected-name", default=EXPECTED_NAME)
    ap.add_argument("--load", action="store_true", help="load the weights and compare class names")
    args = ap.parse_args()
    print(check(args.model_dir, args.expected_name, args.load))


if __name__ == "__main__":
    main()
