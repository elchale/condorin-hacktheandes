# condorin-detection

Detects **illegal-mining vessels** (dredges / barges) on Amazon rivers in very-high-resolution satellite
images in `gs://river-images` and reports every scene to the Condorin backend
(`POST https://api.condorin.pe/api/v1/detections`).

- **Licence:** AGPL-3.0 (the model runs on Ultralytics YOLO, which is AGPL-3.0). The model sits behind a
  swappable `Detector` interface (`src/condorin/core/detector.py`).

## Architecture

```
provider uploads N images to gs://river-images/<river>/<YYYY-MM-DD>T<HHMM>Z_s1.jpeg
        │
        ▼  button or call: POST https://<trigger>/procesar {"prefix": "yaguas/2026-10-18"}
Cloud Run SERVICE condorin-detector-trigger (small, IAM-authenticated):
        validates the prefix, checks it has objects, runs the Job with PREFIX as override → 202
        │
        ▼
Cloud Run JOB condorin-detector (CPU, model baked in): lists gs://river-images/<prefix>*, per image:
        generation + metadata → read that version → QC → tile 640/128 → YOLO → NMS → crops to crops/
        │
        ▼  one call PER IMAGE, also with "detections": []
POST https://api.condorin.pe/api/v1/detections  (Google ID token of condorin-detector@, Idempotency-Key)
```

Why a Job: batches can outlast a request timeout and a Job only bills while it runs. Cloud Scheduler can
later start the same Job once a day. Bucket events (Eventarc) were ruled out: they fire per file, with no
"upload finished" signal.

## Per image

| Step | Rule |
|---|---|
| Generation | Read from the blob metadata; the exact version is downloaded and reported. |
| `river` | First path segment (`yaguas/...` → `yaguas`), must be a slug. |
| `captured_at` | Custom metadata `captured_at`, else the name `<YYYY-MM-DD>T<HHMM>Z` (UTC). |
| `satellite` | Custom metadata `satellite`, else `DEFAULT_SATELLITE` (`SkyFi`). |
| `lat`/`lon` | Box centre mapped linearly inside the scene bounds: custom metadata `bounds` = `{"sw": [lat, lon], "ne": [lat, lon]}`, else `..._sw_<lat>_<lon>_ne_<lat>_<lon>...` in the name. |
| Detections | Positive class (`mining_vessel`) with confidence ≥ `MIN_CONFIDENCE` (default: the model card's `review_low`), strongest 500. |
| `bbox` | `[x, y, w, h]` integer pixels, top-left origin, full image. |
| Crop | PNG of the box + 32 px (min 128 px) at `crops/<object without ext>/<generation>/<model version>/<i>.png`, created only if absent (never overwritten), sent as `gs://river-images/crops/...#<generation>`. |

Every readable image is reported, with or without detections; the backend deduplicates by
`Idempotency-Key: <bucket>/<object>#<generation>`, so re-running a prefix is safe.
An image is **not** reported (and counts as failed) when QC rejects it, `river` or `captured_at` is missing,
or it has detections but no bounds: posting `[]` there would mark a scene with findings as clean.

Logs are JSON for Cloud Logging. Each task ends with
`done: N reported (M with findings), F failed, of T` plus `failures_by_reason`, `duplicates` and `alerted`.
The execution exits non-zero when any image failed.

The backend alerts only for `confidence >= 0.5` and scenes captured within the last 7 days; older or weaker
detections are stored and mapped without alerting.

## Quickstart (fake model, no GCP)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[job,trigger,dev]"
.venv/bin/pytest

# Job against a local folder that stands in for the bucket; the payloads are only logged
mkdir -p /tmp/bucket/yaguas && cp some.jpeg /tmp/bucket/yaguas/2026-10-18T0645Z_s1.jpeg
echo '{"bounds": {"sw": [-2.80, -71.00], "ne": [-2.70, -70.90]}}' \
  > /tmp/bucket/yaguas/2026-10-18T0645Z_s1.jpeg.meta.json   # stands in for GCS custom metadata
FAKE_MODEL=1 WEBHOOK_MODE=log INPUT_BUCKET=/tmp/bucket PREFIX=yaguas/2026-10-18 .venv/bin/python -m condorin.job
```

`FAKE_MODEL=1` never posts to the backend (it refuses unless `ALLOW_FAKE_POST=1`).
For the real model install `torch` (CPU wheel index) and `.[ml]`, and point `MODEL_DIR` at a folder with
`model_card.json` + weights ([`models/README.md`](models/README.md)).

## Configuration

Job (`src/condorin/job/config.py`): `PREFIX` (set per execution by the trigger), `INPUT_BUCKET`,
`WEBHOOK_MODE` (`post` in production, `log` for dry runs), `WEBHOOK_URL`, `MIN_CONFIDENCE`,
`DEFAULT_SATELLITE`, `CROPS_PREFIX`, `MAX_IMAGES`, `MODEL_DIR`. Auth is a Google ID token of the runtime SA
with audience `WEBHOOK_URL`. `DETECTIONS_SHARED_SECRET` (from Secret Manager, never in the repo) is an
optional fallback. Large prefixes can be split across tasks: `gcloud run jobs update condorin-detector
--tasks 4`; each task takes every 4th image.

Trigger (`src/condorin/trigger/app.py`): `GCP_PROJECT`, `GCP_REGION`, `JOB_NAME`, `INPUT_BUCKET`,
`CHECK_PREFIX`.

## Deploy

One time (idempotent; `--dry-run` prints the commands):

```bash
INVOKERS="user:someone@example.org" deploy/gcp-setup.sh
UPDATE_BACKEND=1 deploy/gcp-setup.sh   # adds condorin-detector@ to condorin-api's allowlist (new revision)
```

It creates the SA `condorin-detector@wisecai-consultor-prod.iam.gserviceaccount.com` with `objectViewer`
and `objectCreator` on `river-images` (it can create crops but cannot overwrite or delete anything),
`jobsExecutorWithOverrides` on the Job, and the Job and service with placeholder images and their env vars.
It also lets `github-deployer` act as that SA.

After that, every push to `main` that passes ruff and pytest builds both images to
`us-central1-docker.pkg.dev/wisecai-consultor-prod/cloud-run-source-deploy` and deploys them
(`.github/workflows/ci.yml`, secret `GCP_SA_KEY`). The Job image is built only when the repo variable
`MODEL_GCS_URI` (e.g. `gs://<bucket>/models/v0.3/`) is set; `github-deployer` needs `objectViewer` there.

Start a run:

```bash
URL=$(gcloud run services describe condorin-detector-trigger --region us-central1 --format='value(status.url)')
curl -X POST "$URL/procesar" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' -d '{"prefix": "yaguas/2026-10-18"}'
# → 202 {"execution": "projects/.../executions/condorin-detector-xxxxx", ...}
gcloud run jobs executions list --job condorin-detector --region us-central1
```

Or from GitHub: **Actions → Procesar imágenes → Run workflow** with the prefix
(`.github/workflows/procesar.yml`). It also runs daily at 12:00 UTC for yesterday's date in every river of
the repo variable `RIVERS` (default `yaguas`). It needs the repo variable `TRIGGER_URL` (the trigger's URL).

## Docs

- [`docs/backend-contract.md`](docs/backend-contract.md): the report sent per scene, auth, skip reasons, retries.
- [`docs/runbook.md`](docs/runbook.md): starting and watching runs, failures, large prefixes, model rollout.
- [`models/README.md`](models/README.md): publishing a model to GCS.

## Layout

```
src/condorin/
  core/      model card, tiling, detector (YOLO + fake), NMS, QC, decision, geo/meta, river gate
  io/        storage (gs:// + local)
  job/       Cloud Run Job: listing, per-image processing, crops, backend reporter
  trigger/   Cloud Run service: POST /procesar → run the Job
docker/      job.Dockerfile (CPU + model), trigger.Dockerfile
deploy/      gcp-setup.sh
```

## Licence

Copyright (C) 2026 the Condorin contributors. Licensed under the GNU Affero General Public License v3.0;
see [`LICENSE`](LICENSE). If you run a modified version as a network service, you must offer its source to
the users of that service.
