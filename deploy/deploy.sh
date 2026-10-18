#!/usr/bin/env bash
# Deploy the notifier and the detector to Cloud Run (CPU, scale to zero, concurrency 1).
#
#   PROJECT=my-proj RESULTS_BUCKET=condorin-results \
#   DETECTOR_IMAGE=... NOTIFIER_IMAGE=... deploy/deploy.sh [--dry-run]
#
# Flags checked against `gcloud run deploy --help` (Cloud SDK 542.0.0). Sizing is a starting point:
# tune with scripts/benchmark.py (try 4/8/16 vCPU; memory >= 2x peak RSS).
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

: "${PROJECT:?set PROJECT}"
: "${RESULTS_BUCKET:?set RESULTS_BUCKET}"
: "${DETECTOR_IMAGE:?set DETECTOR_IMAGE}"
: "${NOTIFIER_IMAGE:?set NOTIFIER_IMAGE}"
REGION="${REGION:-southamerica-west1}"
MAX_INSTANCES="${MAX_INSTANCES:-3}"   # open decision: volume per day. Keep queue limits <= this.
CPU="${CPU:-4}"
MEMORY="${MEMORY:-8Gi}"
TIMEOUT="${TIMEOUT:-900}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

DETECTOR_SA="detector-sa@${PROJECT}.iam.gserviceaccount.com"
NOTIFIER_SA="notifier-sa@${PROJECT}.iam.gserviceaccount.com"
TASKS_SA="tasks-invoker-sa@${PROJECT}.iam.gserviceaccount.com"

run() {
  if (( DRY_RUN )); then printf '+'; printf ' %q' "$@"; echo; else "$@"; fi
}

service_url() {
  if (( DRY_RUN )); then echo "https://$1-DRYRUN.a.run.app"; return; fi
  gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || true
}

# 1) notifier: tiny, secrets from Secret Manager (WEBHOOK_URL, WEBHOOK_TOKEN). Never pass the token here.
run gcloud run deploy notifier \
  --project "$PROJECT" --region "$REGION" --image "$NOTIFIER_IMAGE" \
  --no-allow-unauthenticated --service-account "$NOTIFIER_SA" \
  --cpu 1 --memory 512Mi --concurrency 20 --min-instances 0 --max-instances 3 --timeout 60 \
  --set-secrets "WEBHOOK_URL=WEBHOOK_URL:latest,WEBHOOK_TOKEN=WEBHOOK_TOKEN:latest" \
  --set-env-vars "FAILED_DELIVERIES_URI_PREFIX=gs://${RESULTS_BUCKET}/failed_deliveries,LOG_LEVEL=${LOG_LEVEL}"

NOTIFIER_URL="$(service_url notifier)"
DETECTOR_URL="$(service_url detector)"   # empty on the very first deploy; set below

# 2) detector: CPU, request-based billing, scales to zero, one image per instance.
ENV_VARS=(
  "MODEL_DIR=/models/current"
  "FAKE_MODEL=0"
  "DEVICE=cpu"
  "TORCH_THREADS=${CPU}"
  "RESULTS_URI_PREFIX=gs://${RESULTS_BUCKET}/results"
  "OVERLAY_URI_PREFIX=gs://${RESULTS_BUCKET}/overlays"
  "BATCHES_URI_PREFIX=gs://${RESULTS_BUCKET}/batches"
  "FAILED_DELIVERIES_URI_PREFIX=gs://${RESULTS_BUCKET}/failed_deliveries"
  "WEBHOOK_MODE=tasks"
  "DETECT_MODE=tasks"
  "GCP_PROJECT=${PROJECT}"
  "GCP_REGION=${REGION}"
  "DETECT_QUEUE=detect"
  "WEBHOOK_QUEUE=webhook"
  "NOTIFIER_URL=${NOTIFIER_URL}"
  "TASKS_SA_EMAIL=${TASKS_SA}"
  "REQUEST_BUDGET_S=$(( TIMEOUT - 60 ))"
  "TASK_DISPATCH_DEADLINE_S=${TIMEOUT}"
  "LOG_LEVEL=${LOG_LEVEL}"
)
[[ -n "$DETECTOR_URL" ]] && ENV_VARS+=("DETECTOR_URL=${DETECTOR_URL}")
ENV_JOINED="$(IFS="|"; echo "${ENV_VARS[*]}")"

# `^|^` switches the list delimiter to | so values may contain commas (gcloud topic escaping).
run gcloud run deploy detector \
  --project "$PROJECT" --region "$REGION" --image "$DETECTOR_IMAGE" \
  --no-allow-unauthenticated --service-account "$DETECTOR_SA" \
  --cpu "$CPU" --memory "$MEMORY" --concurrency 1 \
  --min-instances 0 --max-instances "$MAX_INSTANCES" --timeout "$TIMEOUT" \
  --cpu-boost \
  --set-env-vars "^|^${ENV_JOINED}"
# Later (GPU, not in South America): --gpu 1 --gpu-type nvidia-l4 --no-cpu-throttling, region with L4.

if [[ -z "$DETECTOR_URL" ]]; then
  DETECTOR_URL="$(service_url detector)"
  run gcloud run services update detector --project "$PROJECT" --region "$REGION" \
    --update-env-vars "DETECTOR_URL=${DETECTOR_URL}"
fi

# 3) invoker bindings (idempotent): Cloud Tasks' OIDC identity may call both services.
for svc in detector notifier; do
  run gcloud run services add-iam-policy-binding "$svc" --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:${TASKS_SA}" --role roles/run.invoker >/dev/null
done
if [[ -n "${DJANGO_SA:-}" ]]; then  # Django's caller identity for POST /batches
  run gcloud run services add-iam-policy-binding detector --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:${DJANGO_SA}" --role roles/run.invoker >/dev/null
fi

echo "detector: ${DETECTOR_URL}"
echo "notifier: ${NOTIFIER_URL}"
