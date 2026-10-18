# Runbook

Project `wisecai-consultor-prod`, region `us-central1`.

| Resource | What it is |
|---|---|
| Cloud Run Job `condorin-detector` | processes `gs://river-images/<PREFIX>*` (CPU, model baked in) |
| Cloud Run service `condorin-detector-trigger` | `POST /procesar {"prefix"}` starts the Job (IAM-authenticated) |
| SA `condorin-detector@` | runs both; reads `river-images`, can create (not overwrite) `crops/` |
| GitHub Actions `CI` | ruff + pytest; on `main` builds and deploys both images |
| GitHub Actions `Procesar imágenes` | starts runs by hand, and daily at 12:00 UTC for yesterday |

Repo variables: `MODEL_GCS_URI` (published model folder), `TRIGGER_URL` (trigger URL), `RIVERS`
(comma-separated rivers for the daily run, default `yaguas`). Secret: `GCP_SA_KEY` (`github-deployer`).

## Starting a run

```bash
URL=$(gcloud run services describe condorin-detector-trigger --region us-central1 --format='value(status.url)')
curl -X POST "$URL/procesar" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' -d '{"prefix": "yaguas/2026-10-18"}'
```

Or **Actions → Procesar imágenes → Run workflow**. The trigger answers 404 if the prefix has no images,
202 with the execution name, the image count and the number of tasks otherwise (see "Large prefixes"). Re-running a prefix is always safe (backend dedupe by
`Idempotency-Key`; crops are write-once).

Without the trigger (operators with Job permissions):

```bash
gcloud run jobs execute condorin-detector --region us-central1 --update-env-vars PREFIX=yaguas/2026-10-18 --wait
```

## Watching a run

```bash
gcloud run jobs executions list --job condorin-detector --region us-central1 --limit 10
gcloud run jobs executions describe <execution> --region us-central1
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="condorin-detector"
  AND jsonPayload.message:"done:"' --project wisecai-consultor-prod --freshness 1d --limit 20 --format json
```

Each task ends with `done: N reported (M with findings), F failed, of T`, plus `failures_by_reason`,
`duplicates`, `alerted`, `gsd_unchecked`, `jev_confirmed`, `jev_rejected` and `report`. The execution fails (non-zero exit) when any image
failed.

Every task also writes a report with each image it did not report and why:

```bash
gcloud storage cat "gs://river-images/reports/<execution>/task-*.json" | jq '.not_reported[]'
```

## A run failed

Read the execution's report (above), or `failures_by_reason` in the `done:` log line and the per-image
`image not reported` lines (`jsonPayload.status` holds the reason, `jsonPayload.image_uri` the scene).

| Reason | Action |
|---|---|
| `no_river`, `no_captured_at` | fix the object path/name or add custom metadata, then re-run the prefix |
| `no_bounds` | add `bounds` custom metadata (or bounds in the name); these scenes **have findings** |
| `rejected_qc` | check the file (truncated, too small, mostly blank, GSD mismatch); replace it if the provider can |
| `bad_gsd_m` | fix the `gsd_m` custom metadata (metres per pixel) |
| `not_started` | the task ran out of time: re-run the prefix (done images are skipped as duplicates) and raise the task count |
| `jev_unavailable` with 401 | the TypeSafe key is wrong or revoked: add a new version of the `typesafe-api-key` secret (below) |
| `jev_unavailable` (other) | TypeSafe was overloaded (`429`/`529`) or unreachable after retries: re-run the prefix |
| `backend_401` / `backend_403` | the SA is not in the backend allowlist: `UPDATE_BACKEND=1 deploy/gcp-setup.sh` |
| `backend_4xx` (other) | payload refused: read `jsonPayload.response` and raise it with the backend team |
| `backend_5xx`, `backend_unreachable`, `storage` | transient: re-run the prefix |
| `no model_card.json` at start | the Job image has no model: publish one and set `MODEL_GCS_URI` |

## Jev validator

Detections ≥ 0.5 are reported only when TypeSafe Jev confirms them (noul ≥ 0.7); see
`docs/backend-contract.md`. What it rejected is in each report:

```bash
gcloud storage cat "gs://river-images/reports/<execution>/task-*.json" | jq '.jev_rejections[]'
```

Turn it on (or rotate the key) without the key touching a file or the shell history:

```bash
read -rs KEY && printf '%s' "$KEY" | gcloud secrets create typesafe-api-key --project wisecai-consultor-prod --data-file=- && unset KEY
deploy/gcp-setup.sh      # grants the Job's SA access, sets JEV_ENABLED=true and TYPESAFE_API_KEY
# rotation: read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add typesafe-api-key --data-file=- && unset KEY
```

Check the key and the request format against the live API before a run (one request):

```bash
TYPESAFE_API_KEY=$(gcloud secrets versions access latest --secret typesafe-api-key) \
  .venv/bin/python scripts/check_jev.py scene.jpg --box 640 320 680 336
```

Turn it off: `gcloud run jobs update condorin-detector --region us-central1 --update-env-vars JEV_ENABLED=false`.
To change the thresholds, set `JEV_TRIGGER_CONFIDENCE` / `JEV_MIN_NOUL` the same way.

## Large prefixes

A task has a 1 h timeout (`--task-timeout` in `deploy/gcp-setup.sh`) and stops starting images 5 min before
it (`TASK_BUDGET_S`). The trigger counts the images under the prefix and runs ceil(images /
`IMAGES_PER_TASK`) tasks, at most `MAX_TASKS` (defaults 200 and 10); each task takes every N-th image.
Set `IMAGES_PER_TASK` from `scripts/benchmark.py` once the real model is deployed:

```bash
gcloud run services update condorin-detector-trigger --region us-central1 --update-env-vars IMAGES_PER_TASK=150
```

A single run can also ask for a task count: `-d '{"prefix": "yaguas/", "tasks": 8}'` (at most `MAX_TASKS`).

## Deploying a new model

See `models/README.md`: upload `best.pt` + `model_card.json` to a new `models/<version>/` folder, set
`MODEL_GCS_URI`, and re-run CI on `main`. The Job image tag is `<git sha>-model<version>`.

Rollback: point the Job at the previous image.

```bash
gcloud run jobs update condorin-detector --region us-central1 \
  --image us-central1-docker.pkg.dev/wisecai-consultor-prod/cloud-run-source-deploy/condorin-detector:<old tag>
```

Also set `MODEL_GCS_URI` back, or the next push to `main` redeploys the newer model.

## Daily schedule

`Procesar imágenes` runs at 12:00 UTC for yesterday (UTC) in every river of `RIVERS`; a river with no
images that day is skipped. It needs `TRIGGER_URL`. To pause it, disable the workflow:
`gh workflow disable "Procesar imágenes"` (re-enable with `gh workflow enable`).

## Measuring the real miss rate

Scenes without findings are reported as clean and never reviewed. To estimate misses, have reviewers check a
random sample of clean scenes regularly; misses found there are also the best new training data.
