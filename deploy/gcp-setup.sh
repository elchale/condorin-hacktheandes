#!/usr/bin/env bash
# One-time, idempotent GCP setup for the detector: service account, bucket IAM, the Cloud Run Job
# `condorin-detector` and the Cloud Run service `condorin-detector-trigger`.
#
#   deploy/gcp-setup.sh --dry-run          # print every command, change nothing
#   deploy/gcp-setup.sh                    # apply
#   INVOKERS="user:ana@example.org,serviceAccount:condorin-gcs@...": who may call POST /procesar
#   UPDATE_BACKEND=1                       # also add the detector SA to the backend's allowlist
#                                          # (deploys a new revision of condorin-api)
#
# Both resources are created with Google's placeholder images; GitHub Actions replaces only the
# image on each push to main. Env vars, SA and resources set here are kept across deploys.
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

PROJECT="${PROJECT:-wisecai-consultor-prod}"
REGION="${REGION:-us-central1}"
INPUT_BUCKET="${INPUT_BUCKET:-river-images}"
JOB="${JOB:-condorin-detector}"
SERVICE="${SERVICE:-condorin-detector-trigger}"
BACKEND_SERVICE="${BACKEND_SERVICE:-condorin-api}"
WEBHOOK_URL="${WEBHOOK_URL:-https://api.condorin.pe/api/v1/detections}"
DEPLOYER_SA="${DEPLOYER_SA:-github-deployer@${PROJECT}.iam.gserviceaccount.com}"
INVOKERS="${INVOKERS:-}"
UPDATE_BACKEND="${UPDATE_BACKEND:-0}"
JOB_CPU="${JOB_CPU:-4}"
JOB_MEMORY="${JOB_MEMORY:-8Gi}"
JOB_TIMEOUT="${JOB_TIMEOUT:-3600s}"

SA_NAME=condorin-detector
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
PLACEHOLDER_JOB_IMAGE=us-docker.pkg.dev/cloudrun/container/job:latest
PLACEHOLDER_SERVICE_IMAGE=us-docker.pkg.dev/cloudrun/container/hello:latest

run() { if (( DRY_RUN )); then printf '+'; printf ' %q' "$@"; echo; else "$@"; fi; }
exists() { (( DRY_RUN )) && return 1; "$@" >/dev/null 2>&1; }

echo "== APIs"
run gcloud services enable --project "$PROJECT" \
  run.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com storage.googleapis.com

echo "== service account ${SA}"
if ! exists gcloud iam service-accounts describe "$SA" --project "$PROJECT"; then
  run gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
    --display-name "condorin detector (Job + trigger)"
fi

echo "== bucket IAM on gs://${INPUT_BUCKET}"
# objectViewer: list and read scenes. objectCreator: create crops under crops/. Without objectAdmin
# the detector cannot overwrite or delete anything, so pinned evidence stays intact.
for role in roles/storage.objectViewer roles/storage.objectCreator; do
  run gcloud storage buckets add-iam-policy-binding "gs://${INPUT_BUCKET}" \
    --member "serviceAccount:${SA}" --role "$role"
done

echo "== GitHub deployer may deploy resources that run as ${SA}"
run gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member "serviceAccount:${DEPLOYER_SA}" --role roles/iam.serviceAccountUser

JOB_ENV="WEBHOOK_MODE=post,INPUT_BUCKET=${INPUT_BUCKET},WEBHOOK_URL=${WEBHOOK_URL}"
echo "== Cloud Run Job ${JOB}"
if exists gcloud run jobs describe "$JOB" --project "$PROJECT" --region "$REGION"; then
  run gcloud run jobs update "$JOB" --project "$PROJECT" --region "$REGION" \
    --service-account "$SA" --update-env-vars "$JOB_ENV" \
    --cpu "$JOB_CPU" --memory "$JOB_MEMORY" --task-timeout "$JOB_TIMEOUT"
else
  # max-retries 0: a failed image fails the execution; re-running the prefix is safe (idempotent).
  run gcloud run jobs create "$JOB" --project "$PROJECT" --region "$REGION" \
    --image "$PLACEHOLDER_JOB_IMAGE" --service-account "$SA" --set-env-vars "$JOB_ENV" \
    --tasks 1 --max-retries 0 --task-timeout "$JOB_TIMEOUT" --cpu "$JOB_CPU" --memory "$JOB_MEMORY"
fi
# The trigger starts executions with a PREFIX override (run.jobs.runWithOverrides).
run gcloud run jobs add-iam-policy-binding "$JOB" --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:${SA}" --role roles/run.jobsExecutorWithOverrides

TRIGGER_ENV="GCP_PROJECT=${PROJECT},GCP_REGION=${REGION},JOB_NAME=${JOB},INPUT_BUCKET=${INPUT_BUCKET}"
echo "== Cloud Run service ${SERVICE}"
if exists gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION"; then
  run gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --service-account "$SA" --update-env-vars "$TRIGGER_ENV"
else
  run gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --image "$PLACEHOLDER_SERVICE_IMAGE" --service-account "$SA" --set-env-vars "$TRIGGER_ENV" \
    --no-allow-unauthenticated --cpu 1 --memory 512Mi --max-instances 2 --concurrency 10
fi
IFS=',' read -ra members <<< "$INVOKERS"
for m in "${members[@]}"; do
  [[ -z "$m" ]] && continue
  run gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --member "$m" --role roles/run.invoker
done

echo "== backend allowlist (DETECTIONS_ALLOWED_SERVICE_ACCOUNTS on ${BACKEND_SERVICE})"
if [[ "$UPDATE_BACKEND" == 1 ]]; then
  current=""
  if (( ! DRY_RUN )); then
    current=$(gcloud run services describe "$BACKEND_SERVICE" --project "$PROJECT" --region "$REGION" \
      --format=json | python3 -c 'import json,sys
for c in json.load(sys.stdin)["spec"]["template"]["spec"]["containers"]:
    for e in c.get("env", []):
        if e["name"] == "DETECTIONS_ALLOWED_SERVICE_ACCOUNTS": print(e.get("value", ""))')
  fi
  if [[ ",${current}," == *",${SA},"* ]]; then
    echo "already allowed: ${SA}"
  else
    merged="${current:+${current},}${SA}"
    # ^;^ makes ; the separator so the comma-separated list survives as one value (emails have @)
    run gcloud run services update "$BACKEND_SERVICE" --project "$PROJECT" --region "$REGION" \
      --update-env-vars "^;^DETECTIONS_ALLOWED_SERVICE_ACCOUNTS=${merged}"
  fi
else
  echo "skipped (set UPDATE_BACKEND=1). Value to add: ${SA}"
fi

cat <<EOF

Done. Next:
  - Push to main: GitHub Actions builds both images and deploys them to ${JOB} and ${SERVICE}.
  - Publish the model and set the repo variable MODEL_GCS_URI (see models/README.md).
  - Run: curl -X POST "\$(gcloud run services describe ${SERVICE} --region ${REGION} --format='value(status.url)')/procesar" \\
           -H "Authorization: Bearer \$(gcloud auth print-identity-token)" \\
           -H 'Content-Type: application/json' -d '{"prefix": "yaguas/2026-10-18"}'
EOF
