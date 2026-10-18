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

Or **Actions → Procesar imágenes → Run workflow**. The trigger answers 404 if the prefix has no objects,
202 with the execution name otherwise. Re-running a prefix is always safe (backend dedupe by
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
`duplicates` and `alerted`. The execution fails (non-zero exit) when any image failed.

## A run failed

Look up `failures_by_reason` in the `done:` log line, then the per-image `image not reported` lines
(`jsonPayload.status` holds the reason, `jsonPayload.image_uri` the scene).

| Reason | Action |
|---|---|
| `no_river`, `no_captured_at` | fix the object path/name or add custom metadata, then re-run the prefix |
| `no_bounds` | add `bounds` custom metadata (or bounds in the name); these scenes **have findings** |
| `rejected_qc` | check the file (truncated, too small, mostly blank); replace it if the provider can |
| `backend_401` / `backend_403` | the SA is not in the backend allowlist: `UPDATE_BACKEND=1 deploy/gcp-setup.sh` |
| `backend_4xx` (other) | payload refused: read `jsonPayload.response` and raise it with the backend team |
| `backend_5xx`, `backend_unreachable`, `storage` | transient: re-run the prefix |
| `no model_card.json` at start | the Job image has no model: publish one and set `MODEL_GCS_URI` |

## Large prefixes

A task has a 1 h timeout (`--task-timeout` in `deploy/gcp-setup.sh`). Split big runs across tasks; each
task takes every N-th image:

```bash
gcloud run jobs update condorin-detector --region us-central1 --tasks 4
```

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
