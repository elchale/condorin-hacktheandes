# Runbook

Region `southamerica-west1`. Services: `detector` (CPU, concurrency 1), `notifier`. Queues: `detect`,
`webhook`. Bucket layout (results bucket):

```
results/<model_version>/<key>.json     one per image × generation × model version
overlays/<model_version>/<key>.jpg     only for detected / needs_review
batches/<batch_id>/manifest.json
failed_deliveries/<sha1(idempotency_key)>.json
```

Logs are JSON in Cloud Logging; filter with `jsonPayload.batch_id="..."`, `jsonPayload.idempotency_key="..."`,
`jsonPayload.image_uri="..."`.

## Submitting work

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST "$DETECTOR_URL/batches" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"batch_id": "yaguas-2026-10-15", "prefix": "gs://river-images/yaguas/", "limit": 100}'
curl -s "$DETECTOR_URL/batches/yaguas-2026-10-15" -H "Authorization: Bearer $TOKEN" | jq .counts
```

Resubmitting a batch is safe: generations are pinned, results are skipped if present, task names are
deterministic. `scripts/smoke_test.py --base-url $DETECTOR_URL --id-token $TOKEN --prefix ...` does the same.

## Queue backed up (`detect`)

1. `gcloud tasks queues describe detect --location southamerica-west1` (rate limits, state).
2. Detector errors? Logs with `severity>=WARNING` on `detector`. A 503 storm usually means GCS throttling
   or the request budget (`REQUEST_BUDGET_S`) being hit: check `timings_ms.inference`.
3. Throughput is `max-instances` × (1 / seconds per image). To go faster raise `--max-instances` on the
   detector **and** `--max-concurrent-dispatches` on the queue together (queue ≤ instances).
4. Pause/resume: `gcloud tasks queues pause|resume detect --location southamerica-west1`.

## Webhook failures

- **`webhook auth rejected` (401/403)**: the token was rotated or is missing. Tasks keep retrying (72 h).
  Add the new value: `printf '%s' "$NEW" | gcloud secrets versions add WEBHOOK_TOKEN --data-file=-`,
  then redeploy the notifier (`--set-secrets ...:latest` is resolved at instance start) or wait for new instances.
- **Dead-lettered deliveries** (other 4xx, including 409): `gcloud storage ls gs://$RESULTS_BUCKET/failed_deliveries/`.
  Each file has the event, Django's status and a response snippet. Fix the cause, then replay (below).
- Tasks that exhausted retries are dropped by Cloud Tasks. Their results are still in `results/`: replay them.

## Replaying an event

The task name `deliver-<sha1(key + model_version)>` cannot be reused for a while after it ran (VERIFY the
dedupe window in the Cloud Tasks docs), so a replay uses a new suffix:

```bash
F=gs://$RESULTS_BUCKET/failed_deliveries/<sha1>.json
gcloud storage cat $F | jq '{event: .event}' > /tmp/event.json
gcloud tasks create-http-task "replay-$(date +%s)-$(sha1sum <<<"$F" | cut -c1-8)" \
  --queue webhook --location southamerica-west1 \
  --url "$NOTIFIER_URL/deliver" --method POST \
  --header "Content-Type: application/json" --body-file /tmp/event.json \
  --oidc-service-account-email "tasks-invoker-sa@$PROJECT.iam.gserviceaccount.com"
```

For a result without a dead-letter file, rebuild the event from `results/<version>/<key>.json`
(`condorin.notifier.payload.build_webhook_payload`) or simply re-POST the image to `/detect`: an existing
result skips compute and re-enqueues the webhook (deduplicated by task name while the name is reserved).

## Deploying a new model version

1. Publish: `gcloud storage cp best.pt model_card.json gs://$MODEL_BUCKET/models/$VERSION/` (see `models/README.md`).
   Check that the card validates and its thresholds come from the evaluation (`threshold.json`).
2. Build + deploy:
   ```bash
   gcloud builds submit --region southamerica-west1 --config deploy/cloudbuild.yaml \
     --substitutions=_MODEL_BUCKET=$MODEL_BUCKET,_MODEL_VERSION=$VERSION,_RESULTS_BUCKET=$RESULTS_BUCKET,_TAG=$(git rev-parse --short HEAD)
   ```
   The image tag is `<code>-model<version>`; rollback = redeploy the previous tag
   (`gcloud run services update-traffic detector --to-revisions <rev>=100`).
3. Shadow compare (Phase 7): run the candidate on a recent batch with `WEBHOOK_MODE=log` (or a separate
   results prefix) and compare decisions/scores per image before switching.
4. Results are namespaced by model version, so the new model re-processes images; note that Django sees the
   same `Idempotency-Key` for the same image generation (open point in `docs/webhook.md`).

## Measuring the real miss rate

`clear` images are sampled for review at `AUDIT_RATE` (default 1%), flagged `audit_sample: true` in the
result. Review them; misses found there are the production false-negative rate and new training data.

## Secrets

`WEBHOOK_TOKEN` and `WEBHOOK_URL` live only in Secret Manager. Never put them in env files, CI, chat or logs.
If a token is ever exposed (pasted anywhere), rotate it with the Django team and add a new secret version.
