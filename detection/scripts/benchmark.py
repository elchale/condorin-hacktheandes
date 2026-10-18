#!/usr/bin/env python
"""Inference benchmark: tiles/s, seconds/image and estimated Cloud Run cost per 1,000 images, so the
CPU vs GPU decision is made on data. Optionally reports presence recall separately for JPG and PNG.

    # real model (MODEL_DIR with model_card.json + weights), synthetic 2560 px images
    MODEL_DIR=/path/to/model python scripts/benchmark.py --size 2560 --images 5 --vcpu 4 --mem-gib 8
    # recall per format on a labelled test set (CSV: path,has_vessel with 1/0)
    MODEL_DIR=... python scripts/benchmark.py --labels test_set.csv

Prices are inputs: take them from the Cloud Run pricing page for your region's tier
(southamerica-west1 is Tier 2) and billing mode. Defaults are placeholders, NOT verified prices.
"""

from __future__ import annotations

import argparse
import csv
import os
import resource
import statistics
import time
from pathlib import Path

import numpy as np

from condorin.core.decision import presence_score
from condorin.core.detector import build_detector
from condorin.core.model_card import ModelCard, load_model_card
from condorin.core.qc import run_qc
from condorin.core.tiling import tile_offsets
from condorin.job.config import JobSettings


def load(settings: JobSettings) -> tuple:
    if Path(settings.model_dir, "model_card.json").is_file():
        card = load_model_card(settings.model_dir)
    else:
        card = ModelCard.placeholder()
        settings.fake_model = True
        print("no model card in MODEL_DIR: benchmarking the FAKE detector (pipeline overhead only)")
    return card, build_detector(settings, card)


def bench(args, card, det) -> None:
    rng = np.random.default_rng(0)
    t = card.inference
    n_tiles = len(tile_offsets(args.size, args.size, t.tile, t.overlap))
    det.detect(rng.integers(0, 255, (t.tile, t.tile, 3), dtype=np.uint8))  # warm-up
    times = []
    for _ in range(args.images):
        img = rng.integers(0, 255, (args.size, args.size, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        det.detect(img)
        times.append(time.perf_counter() - t0)
    med = statistics.median(times)
    rss_gib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2
    per_img_cost = med * (args.vcpu * args.price_vcpu_s + args.mem_gib * args.price_gib_s)
    if args.gpu:
        per_img_cost += med * args.price_gpu_s
    print(f"device={det.device} size={args.size}px tiles/image={n_tiles} vcpu={args.vcpu} "
          f"torch_threads={os.environ.get('TORCH_THREADS', 'default')}")  # fmt: skip
    print(f"seconds/image: median {med:.2f}  min {min(times):.2f}  max {max(times):.2f}")
    print(f"tiles/second:  {n_tiles / med:.1f}")
    print(f"peak RSS:      {rss_gib:.2f} GiB (set memory >= 2x)")
    print(f"est. cost per 1,000 images (compute only, excl. cold starts/requests): "
          f"${per_img_cost * 1000:.3f}")  # fmt: skip


def recall_by_format(args, card, det) -> None:
    with open(args.labels, newline="") as f:
        rows = list(csv.DictReader(f))
    stats: dict = {}
    for row in rows:
        path = Path(row["path"])
        positive = row["has_vessel"].strip() in ("1", "true", "yes")
        fmt = "png" if path.suffix.lower() == ".png" else "jpg"
        qc = run_qc(path.read_bytes(), card.qc)
        score = presence_score(det.detect(qc.image_bgr), card.positive_class) if qc.passed else 0.0
        s = stats.setdefault(fmt, {"pos": 0, "tp": 0, "neg": 0, "fp": 0})
        if positive:
            s["pos"] += 1
            s["tp"] += score >= card.thresholds.detect
        else:
            s["neg"] += 1
            s["fp"] += score >= card.thresholds.detect
    for fmt, s in sorted(stats.items()):
        rec = s["tp"] / s["pos"] if s["pos"] else float("nan")
        fpr = s["fp"] / s["neg"] if s["neg"] else float("nan")
        print(f"{fmt}: recall {rec:.3f} ({s['tp']}/{s['pos']})  false-positive rate {fpr:.3f} "
              f"({s['fp']}/{s['neg']}) at detect={card.thresholds.detect}")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--size", type=int, default=2560)
    ap.add_argument("--images", type=int, default=5)
    ap.add_argument("--vcpu", type=float, default=4)
    ap.add_argument("--mem-gib", type=float, default=8)
    ap.add_argument("--gpu", action="store_true", help="add the GPU price to the cost estimate")
    ap.add_argument(
        "--price-vcpu-s", type=float, default=0.000024, help="USD per vCPU-second (placeholder)"
    )
    ap.add_argument(
        "--price-gib-s", type=float, default=0.0000025, help="USD per GiB-second (placeholder)"
    )
    ap.add_argument(
        "--price-gpu-s", type=float, default=0.0002, help="USD per GPU-second (placeholder)"
    )
    ap.add_argument("--labels", help="CSV with columns path,has_vessel for per-format recall")
    args = ap.parse_args()

    card, det = load(JobSettings())
    if args.labels:
        recall_by_format(args, card, det)
    else:
        bench(args, card, det)


if __name__ == "__main__":
    main()
