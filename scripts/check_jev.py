#!/usr/bin/env python
"""Send one real request to TypeSafe Jev with the Job's exact format, to check the key, headers and
answer before deploying. Reads TYPESAFE_API_KEY from the environment (never pass it as an argument).

    TYPESAFE_API_KEY=$(gcloud secrets versions access latest --secret typesafe-api-key) \\
      .venv/bin/python scripts/check_jev.py scene.jpg --box 640 320 680 336

Without --box the crop is taken at the image centre. Prints the model that answered, the noul,
whether it passes JEV_MIN_NOUL, and the token usage. One request costs a few thousand input tokens.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from condorin.core.detector import Detection
from condorin.job.config import JobSettings
from condorin.job.validator import JevValidator, ValidatorError


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--box", type=float, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    args = ap.parse_args()

    img = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if img is None:
        print(f"cannot read {args.image}", file=sys.stderr)
        return 2
    h, w = img.shape[:2]
    box = tuple(args.box) if args.box else (w / 2 - 20, h / 2 - 8, w / 2 + 20, h / 2 + 8)
    settings = JobSettings(jev_enabled=True)
    try:
        validator = JevValidator(settings)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    body, parts = validator.build_request(img, [Detection("mining_vessel", 1.0, box)])
    try:
        answer = validator.ask(body, parts)
    except ValidatorError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    noul = answer["answers"]["candidate_0"]["noul"]
    print(f"model={answer.get('model')} noul={noul:.3f} "
          f"passes={noul >= settings.jev_min_noul} (JEV_MIN_NOUL={settings.jev_min_noul}) "
          f"usage={answer.get('usage')}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
