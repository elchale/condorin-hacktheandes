# Webhook contract: condorin → Django

The Django team fixed this contract. **Do not rename fields.** Code: `src/condorin/notifier/payload.py`
(mapping) and `src/condorin/notifier/delivery.py` (HTTP). Reference receiver: `docs/examples/django_webhook_receiver/`.

## Request

```
POST https://api.condorin.pe/api/v1/detections        (WEBHOOK_URL, from Secret Manager)
Authorization: Bearer <WEBHOOK_TOKEN>                 (Secret Manager; never logged, never in git)
Idempotency-Key: <bucket>/<object>#<generation>
Content-Type: application/json
```

```json
{
  "image": {
    "bucket": "river-images",
    "object": "yaguas/2026-10-15T1042Z_s1.jpeg",
    "generation": "1792297654023751",
    "river": "yaguas",
    "satellite": "Skyfi",
    "captured_at": "2026-10-15T10:42:00Z"
  },
  "model": {"name": "dredge-detector", "version": "v0.3"},
  "detections": [
    {"lat": -2.7706, "lon": -70.9512, "confidence": 0.87,
     "bbox": [412, 318, 14, 9],
     "crop_uri": "gs://river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"}
  ]
}
```

The body is serialised once (compact JSON, UTF-8) and those exact bytes are sent. There is no HMAC
signature in this contract; authentication is the bearer token only.

## Fields

| Field | Source |
|---|---|
| `image.bucket/object/generation` | the job; `generation` is the GCS generation pinned when the batch was accepted |
| `image.river` | job `options.river` > GCS object metadata `river` > first path segment of the object > `null` |
| `image.satellite` | job `options.satellite` > GCS object metadata `satellite` > `null` |
| `image.captured_at` | job option > object metadata > `YYYY-MM-DDTHHMMZ` in the object name > `null` (UTC, ISO-8601 with `Z`) |
| `model.name/version` | `model_card.json` (`name` should be `dredge-detector`) |
| `detections[].confidence` | model confidence, rounded to 4 decimals |
| `detections[].bbox` | `[x, y, w, h]` in pixels of the **full original image**, `x,y` = top-left corner |
| `detections[].lat/lon` | centre of the box, linearly interpolated inside the image bounds (see below) |
| `detections[].crop_uri` | the source image URI with `#generation` (`CROP_URI_MODE=source`) |

### How `lat`/`lon` are derived

Images are JPG/PNG with no geo metadata, so the image **bounds** (south-west and north-east corners) come
from, in priority order: job `options.bounds` (`{"sw": [lat, lon], "ne": [lat, lon]}`), GCS object
metadata `bounds` (same JSON as a string), or the object name pattern `sw_<lat>_<lon>_ne_<lat>_<lon>`
(e.g. `tile_r003_c004_sw_-2.78_-70.97_ne_-2.77_-70.96.jpg`). The box centre is mapped linearly
(extents are under 1 km, so projection distortion is negligible); image `y` grows southwards. For a
truncated image the full decoded height is used, so the mapping stays correct. Without bounds,
`lat`/`lon` are `null` and a `WARNING` is logged.

## When a webhook is sent

- Only detections of the positive class (`mining_vessel`) with `confidence >= WEBHOOK_MIN_CONFIDENCE`
  (default: the model card's `review_low`). `other_vessel` boxes stay in `result.json` only.
- Only if at least one detection remains (`SEND_EMPTY=false`). Images with no detections, QC rejections
  and failures send nothing; they are recorded in `result.json` and in the batch summary.
- There is no decision field: Django applies its own thresholds on `confidence`
  (the model card's `detect` threshold is the recall-0.95 operating point).

## Delivery semantics

Delivery is **at least once**: Django must dedupe on `Idempotency-Key` and answer 2xx for duplicates.
One Cloud Task per image, named `deliver-sha1(idempotency_key + model_version)`, so duplicate enqueues
are rejected by Cloud Tasks.

| Django response | Notifier returns to Cloud Tasks | Effect |
|---|---|---|
| 2xx | 200 | done |
| network error / timeout (10 s) | 503 | retried with backoff |
| 408, 429, 5xx | 503 | retried with backoff |
| 401, 403 | 503 + `ERROR "webhook auth rejected"` | retried: usually a rotated/missing token; nothing is lost once fixed |
| other 4xx (400, 404, 409, 422…) | 200 + `ERROR` | permanent: written to `failed_deliveries/<sha1(key)>.json` |

The `webhook` queue retries for up to 72 h (see `deploy/infra/setup.sh`).

## Open points to confirm with the Django team

1. **409**: is it "duplicate" (should count as success)? Currently a permanent failure (dead-lettered).
2. **Idempotency-Key has no model version.** Re-processing the same image generation with a new model
   sends the same key, so Django would treat it as a duplicate unless it keys on key + `model.version`.
3. **bbox convention** `[x, y, w, h]`, top-left origin, full-image pixels. The example `[412, 318, 14, 9]`
   is smaller than the vessels seen in training (about 25-60 px long).
4. **crop_uri**: the example repeats the source image URI. Should it be a real per-detection crop?
5. **null lat/lon**: are they accepted when bounds are unknown?
6. Which detections to send (only `mining_vessel` ≥ `review_low`?) and whether empty results should be sent.
7. Django's rate limits (sets the `webhook` queue rate).
