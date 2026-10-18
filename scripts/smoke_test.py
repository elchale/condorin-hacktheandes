#!/usr/bin/env python
"""End-to-end smoke test: POST a batch to /batches, poll GET /batches/{id}, print webhook payloads.

Local (detector started with `make run-local`, FAKE_MODEL=1, WEBHOOK_MODE=log):
    python scripts/smoke_test.py --base-url http://127.0.0.1:8080 --make-images 5

Deployed (Cloud Run IAM; uses your identity token):
    python scripts/smoke_test.py --base-url https://detector-xxx.a.run.app \
        --id-token "$(gcloud auth print-identity-token)" --prefix gs://river-images/yaguas/ --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from condorin.io import storage
from condorin.notifier.payload import build_webhook_payload


def make_images(out_dir: Path, n: int, size: int = 1280) -> list[str]:
    """Synthetic river scenes named like the user's tiles (bounds in the name → lat/lon)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    uris = []
    for i in range(n):
        rng = np.random.default_rng(i)
        img = np.clip(np.full((size, size, 3), (40, 90, 40)) + rng.integers(-25, 25, (size, size, 3)),
                      0, 255).astype(np.uint8)  # fmt: skip
        y0 = size // 3
        img[y0 : y0 + size // 6] = (170, 140, 100)
        lat, lon = -2.78 + 0.01 * i, -70.97
        name = (f"2026-10-15T1042Z_tile_r{i:03d}_c000_sw_{lat:.6f}_{lon:.6f}"
                f"_ne_{lat + 0.009:.6f}_{lon + 0.009:.6f}.jpg")  # fmt: skip
        path = out_dir / name
        Image.fromarray(img).save(path, quality=92)
        uris.append(str(path.resolve()))
    return uris


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--id-token", help="identity token for Cloud Run IAM (Authorization: Bearer)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--make-images", type=int, metavar="N", help="generate N local fake images")
    src.add_argument("--images", nargs="+", metavar="URI")
    src.add_argument("--prefix", help="gs:// or local prefix to list")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--out", default="out/smoke/images/yaguas")
    ap.add_argument("--batch-id")
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.id_token}"} if args.id_token else {}
    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=60)

    if args.prefix:
        body: dict = {"prefix": args.prefix, "limit": args.limit}
    else:
        uris = args.images or make_images(Path(args.out), args.make_images or 5)
        body = {"images": [{"uri": u} for u in uris]}
    if args.batch_id:
        body["batch_id"] = args.batch_id

    r = client.post("/batches", json=body)
    print(f"POST /batches -> {r.status_code} {r.text}")
    if r.status_code != 202:
        return 1
    batch_id = r.json()["batch_id"]

    deadline = time.monotonic() + args.timeout
    while True:
        s = client.get(f"/batches/{batch_id}").json()
        print(f"  counts: {json.dumps(s['counts'])}")
        if s["complete"] or time.monotonic() > deadline:
            break
        time.sleep(2)
    if not s["complete"]:
        print("timed out waiting for the batch", file=sys.stderr)
        return 1

    print("\nwebhook payloads produced:")
    n = 0
    for item in s["items"]:
        if not (item.get("webhook") or {}).get("sent"):
            continue
        try:
            result = storage.read_json(item["result_uri"])  # works for local and gs:// (with ADC)
        except Exception as err:  # noqa: BLE001
            print(f"  (cannot read {item['result_uri']}: {err})")
            continue
        payload = build_webhook_payload(result)
        print(f"Idempotency-Key: {result['idempotency_key']}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        n += 1
    print(f"\n{s['counts']['done']} images processed, {n} webhook event(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
