# condorin-detection

Detects **illegal-mining vessels** (dredges / barges) on Amazon rivers in very-high-resolution satellite
images (JPG/PNG in Google Cloud Storage) and reports them to the Condorin Django backend by webhook.

- **Primary output:** image-level presence (`detected` / `needs_review` / `clear`) with a confidence score.
- **Secondary output:** vessel bounding boxes, mapped to `lat`/`lon` when the image bounds are known.
- **Licence:** AGPL-3.0 (the detector uses Ultralytics YOLO, which is AGPL-3.0). The running detector links
  to this source at `GET /`. The model sits behind a swappable `Detector` interface.

## Architecture

```
Django ──(gs:// URIs, ≤100)──▶ POST /batches (detector)  ── one Cloud Task per image ──▶ queue "detect"
                                                                                        │ POST /detect
         Cloud Run "detector" (CPU, concurrency 1): read → QC → tile 640/128 → YOLO → cross-tile NMS → decide
                    │ writes results/{model_version}/{key}.json (+ overlay.jpg) to GCS
                    └── Cloud Task (deterministic name) ──▶ queue "webhook" ──▶ Cloud Run "notifier" POST /deliver
                                                                                        │ Bearer + Idempotency-Key
                                                         Django POST https://api.condorin.pe/api/v1/detections
```

Results are stored before delivery, so webhook retries never hold a detector instance, and replays and
dead-lettering are simple. Details: [`docs/webhook.md`](docs/webhook.md) (contract),
[`docs/runbook.md`](docs/runbook.md) (operations).

## Quickstart (fake model, no GCP needed)

```bash
make install        # uv venv + CPU torch + package with [serve,dev]
make test           # pytest; no GPU, weights or GCS needed (make lint for ruff)
make run-local      # FAKE_MODEL=1, results in ./out, webhook events only logged
# in another shell:
make smoke          # generates 5 fake images, POSTs a batch, polls GET /batches/{id}, prints webhook payloads
make django-test    # example Django receiver tests (needs `pip install django`)
```

Single image (after `make smoke` generated some):

```bash
IMG=$(ls out/smoke/images/yaguas/*.jpg | head -1)
curl -s localhost:8080/detect -H 'content-type: application/json' -d "{\"image_uri\": \"$IMG\"}" | jq
```

`image_uri` accepts `gs://bucket/object`, `file:///abs/path` or a local path.

## Inference contract

Matches how the model was evaluated in the (separate) training toolkit:

1. Decode with QC (strict decode; truncated files fall back to a tolerant decode and are processed if at most
   `max_truncated_lost_fraction` of the rows were lost).
2. Tile at native resolution (640 px tiles, 128 px overlap); never downscale the full image.
3. YOLO per tile (`conf` floor 0.05, `iou` 0.6), shift boxes, class-aware NMS at IoU 0.5 across tiles.
4. Score = max confidence of `mining_vessel`; thresholds from `model_card.json`:
   `score >= detect` → `detected`, `>= review_low` → `needs_review`, else `clear`.
5. A small random share of `clear` images (`AUDIT_RATE`, default 1%) is flagged `audit_sample: true`.

## Layout

```
src/condorin/
  config.py          settings from env vars
  core/              model card, tiling, detector (YOLO + fake), NMS, QC, decision, geo/meta, river gate
  io/                storage (gs:// + local), overlay rendering
  service/           detector FastAPI app: /detect, /batches, /healthz, /readyz
  notifier/          webhook payload mapping + notifier FastAPI app: /deliver
docker/              detector (CPU) and notifier Dockerfiles
deploy/              Cloud Build, Cloud Run deploy script, idempotent infra setup (gcloud)
docs/                webhook contract, runbook, Django receiver example
scripts/             smoke test, CPU/GPU benchmark
models/README.md     how to publish a model (weights never in git)
```

## Configuration

All settings are environment variables; see `src/condorin/config.py`.
The webhook bearer token lives only in Secret Manager (`WEBHOOK_TOKEN`) and is never logged.

## Licence

Copyright (C) 2026 the Condorin contributors. Licensed under the GNU Affero General Public License v3.0;
see [`LICENSE`](LICENSE). If you run a modified version as a network service, you must offer its source to
the users of that service.
