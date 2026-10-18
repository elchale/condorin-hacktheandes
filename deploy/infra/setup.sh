#!/usr/bin/env bash
# Idempotent infrastructure setup for condorin (region southamerica-west1 / Santiago).
#
#   PROJECT=my-proj INPUT_BUCKET=river-images RESULTS_BUCKET=condorin-results \
#   [DJANGO_SA=django@other.iam.gserviceaccount.com] deploy/infra/setup.sh [--dry-run]
#
# Creates: APIs, service accounts, results bucket, Artifact Registry repo, Cloud Tasks queues,
# empty secrets, IAM. It NEVER takes the webhook token as input: add secret values yourself with
#   printf '%s' "$TOKEN" | gcloud secrets versions add WEBHOOK_TOKEN --data-file=-
# Flags checked against `gcloud ... --help` (Cloud SDK 542.0.0). Items still marked VERIFY are
# product behaviours, not flag names.
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

: "${PROJECT:?set PROJECT}"
: "${INPUT_BUCKET:?set INPUT_BUCKET (the bucket with the satellite images)}"
: "${RESULTS_BUCKET:?set RESULTS_BUCKET}"
REGION="${REGION:-southamerica-west1}"
AR_REPO="${AR_REPO:-condorin}"
MAX_INSTANCES="${MAX_INSTANCES:-3}"   # detect queue concurrency must stay <= detector max-instances

DETECTOR_SA="detector-sa@${PROJECT}.iam.gserviceaccount.com"
NOTIFIER_SA="notifier-sa@${PROJECT}.iam.gserviceaccount.com"
TASKS_SA="tasks-invoker-sa@${PROJECT}.iam.gserviceaccount.com"

run() {
  if (( DRY_RUN )); then printf '+'; printf ' %q' "$@"; echo; else "$@"; fi
}
# exists <cmd...>: true if the describe command succeeds. In dry-run, assume nothing exists.
exists() {
  (( DRY_RUN )) && return 1
  "$@" >/dev/null 2>&1
}

echo "== preflight: products offered in ${REGION}"
if (( ! DRY_RUN )); then
  gcloud run regions list --project "$PROJECT" --format='value(locationId)' | grep -qx "$REGION" \
    || { echo "Cloud Run is not offered in $REGION" >&2; exit 1; }
  gcloud tasks locations list --project "$PROJECT" --format='value(locationId)' | grep -qx "$REGION" \
    || { echo "Cloud Tasks is not offered in $REGION: STOP and decide with the team (see CLAUDE.md)." >&2; exit 1; }
  gcloud artifacts locations list --project "$PROJECT" --format='value(name)' | grep -qx "$REGION" \
    || { echo "Artifact Registry is not offered in $REGION" >&2; exit 1; }
  # Secret Manager user-managed replication location: VERIFY (secrets create fails clearly if not).
else
  echo "(dry-run: skipped region checks: gcloud run regions list / tasks locations list / artifacts locations list)"
fi

echo "== APIs"
run gcloud services enable --project "$PROJECT" \
  run.googleapis.com cloudtasks.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com storage.googleapis.com iamcredentials.googleapis.com

echo "== service accounts"
for sa in detector-sa notifier-sa tasks-invoker-sa; do
  if ! exists gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" --project "$PROJECT"; then
    run gcloud iam service-accounts create "$sa" --project "$PROJECT" --display-name "condorin ${sa}"
  fi
done

echo "== results bucket"
if ! exists gcloud storage buckets describe "gs://${RESULTS_BUCKET}" --project "$PROJECT"; then
  run gcloud storage buckets create "gs://${RESULTS_BUCKET}" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi

echo "== bucket IAM"
run gcloud storage buckets add-iam-policy-binding "gs://${INPUT_BUCKET}" \
  --member "serviceAccount:${DETECTOR_SA}" --role roles/storage.objectViewer
# objectAdmin: results are created, read, listed and the batch manifest may be overwritten.
run gcloud storage buckets add-iam-policy-binding "gs://${RESULTS_BUCKET}" \
  --member "serviceAccount:${DETECTOR_SA}" --role roles/storage.objectAdmin
run gcloud storage buckets add-iam-policy-binding "gs://${RESULTS_BUCKET}" \
  --member "serviceAccount:${NOTIFIER_SA}" --role roles/storage.objectAdmin

echo "== Artifact Registry"
if ! exists gcloud artifacts repositories describe "$AR_REPO" --project "$PROJECT" --location "$REGION"; then
  run gcloud artifacts repositories create "$AR_REPO" --project "$PROJECT" --location "$REGION" \
    --repository-format docker --description "condorin images"
fi

echo "== Cloud Tasks queues"
# detect: one image per detector instance; <= max-instances. Retries with backoff.
DETECT_FLAGS=(--max-dispatches-per-second 1 --max-concurrent-dispatches "$MAX_INSTANCES"
              --max-attempts 5 --min-backoff 30s --max-backoff 600s)
# webhook: Django is fast (2xx then Celery). Long retry window so a rotated token (401) loses nothing.
# VERIFY the maximum allowed --max-retry-duration and the task-name dedupe window in the Cloud Tasks docs.
WEBHOOK_FLAGS=(--max-dispatches-per-second 5 --max-concurrent-dispatches 5
               --max-attempts 100 --min-backoff 10s --max-backoff 3600s --max-retry-duration 72h)
for q in detect webhook; do
  if [[ "$q" == detect ]]; then flags=("${DETECT_FLAGS[@]}"); else flags=("${WEBHOOK_FLAGS[@]}"); fi
  if exists gcloud tasks queues describe "$q" --project "$PROJECT" --location "$REGION"; then
    run gcloud tasks queues update "$q" --project "$PROJECT" --location "$REGION" "${flags[@]}"
  else
    run gcloud tasks queues create "$q" --project "$PROJECT" --location "$REGION" "${flags[@]}"
  fi
done

echo "== secrets (created empty; values are added by a human)"
for s in WEBHOOK_TOKEN WEBHOOK_URL; do
  if ! exists gcloud secrets describe "$s" --project "$PROJECT"; then
    run gcloud secrets create "$s" --project "$PROJECT" \
      --replication-policy user-managed --locations "$REGION"
  fi
  run gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
    --member "serviceAccount:${NOTIFIER_SA}" --role roles/secretmanager.secretAccessor
done

echo "== project/SA IAM"
# The detector creates Cloud Tasks...
run gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${DETECTOR_SA}" --role roles/cloudtasks.enqueuer --condition None
# ...that carry an OIDC token for tasks-invoker-sa, which needs actAs on that SA.
run gcloud iam service-accounts add-iam-policy-binding "$TASKS_SA" --project "$PROJECT" \
  --member "serviceAccount:${DETECTOR_SA}" --role roles/iam.serviceAccountUser
# VERIFY: older projects may also need the Cloud Tasks service agent to hold
# roles/iam.serviceAccountTokenCreator on tasks-invoker-sa.

cat <<EOF

Done. Next steps:
  1. Add the secret values (never paste the token into files or chat):
       printf '%s' "https://api.condorin.pe/api/v1/detections" | gcloud secrets versions add WEBHOOK_URL --project $PROJECT --data-file=-
       printf '%s' "\$WEBHOOK_TOKEN" | gcloud secrets versions add WEBHOOK_TOKEN --project $PROJECT --data-file=-
  2. Build and deploy: gcloud builds submit --region $REGION --config deploy/cloudbuild.yaml --substitutions=...
     (deploy/deploy.sh grants roles/run.invoker to ${TASKS_SA} and to DJANGO_SA on the services)
EOF
