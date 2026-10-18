# Backend contract: detector → Condorin API

The Cloud Run Job `condorin-detector` reports **every readable scene** to the backend, one call per image.
Code: `src/condorin/job/runner.py` (payload) and `src/condorin/job/report.py` (HTTP).
The field names are fixed by the backend team; do not rename them.

## Request

```
POST https://api.condorin.pe/api/v1/detections            (WEBHOOK_URL)
Authorization: Bearer <Google ID token of condorin-detector@, audience = WEBHOOK_URL>
Idempotency-Key: <bucket>/<object>#<generation>
Content-Type: application/json
```

The backend accepts the token only if the service account is in its `DETECTIONS_ALLOWED_SERVICE_ACCOUNTS`
allowlist (`UPDATE_BACKEND=1 deploy/gcp-setup.sh` adds it). `DETECTIONS_SHARED_SECRET` (Secret Manager,
never in the repo) is an optional fallback bearer; when it is set, no ID token is minted.

```json
{
  "image": {
    "bucket": "river-images",
    "object": "yaguas/2026-10-15T1042Z_s1.jpeg",
    "generation": "1792297654023751",
    "river": "yaguas",
    "satellite": "SkyFi",
    "captured_at": "2026-10-15T10:42:00Z"
  },
  "model": {"name": "dredge-detector", "version": "2026-10-r1"},
  "detections": [
    {"lat": -2.7706, "lon": -70.9512, "confidence": 0.87,
     "bbox": [412, 318, 45, 57],
     "crop_uri": "gs://river-images/crops/yaguas/2026-10-15T1042Z_s1/1792297654023751/2026-10-r1/000.png#1792297700000000"}
  ]
}
```

A scene with no findings is sent with `"detections": []`; the backend stores it as reviewed and clean.

## Fields

| Field | Source |
|---|---|
| `image.bucket/object/generation` | the listed object; the generation is read first and exactly that version is downloaded |
| `image.river` | first path segment of the object, lower-cased; must be a slug |
| `image.satellite` | GCS custom metadata `satellite`, else `DEFAULT_SATELLITE` (`SkyFi`) |
| `image.captured_at` | custom metadata `captured_at`, else `<YYYY-MM-DD>T<HHMM>Z` in the name (UTC, ISO-8601 with `Z`) |
| `model.name/version` | `model_card.json` baked into the image |
| `detections[]` | positive class (`mining_vessel`) with `confidence >= MIN_CONFIDENCE` (default: the card's `review_low`), strongest first, at most 500 |
| `confidence` | model confidence, 4 decimals |
| `bbox` | `[x, y, w, h]` integer pixels of the full original image, top-left origin |
| `lat`/`lon` | box centre, linear interpolation inside the scene bounds (below) |
| `crop_uri` | PNG of the box plus 32 px (at least 128 px), written once to `crops/<object without ext>/<generation>/<model version>/<i>.png`, with its own `#generation` |

### Bounds

JPG/PNG scenes carry no geo metadata. Bounds come from custom metadata `bounds`
(`{"sw": [lat, lon], "ne": [lat, lon]}` as a JSON string), else from `..._sw_<lat>_<lon>_ne_<lat>_<lon>...`
in the object name. Extents are under 1 km, so the linear mapping is accurate enough; image `y` grows
southwards. For a truncated image the full decoded height is used.

## When a scene is **not** reported

Posting would be wrong in these cases, so the image is skipped and counted as failed (the execution exits
non-zero). Reason codes appear in the logs and in `failures_by_reason`:

| Reason | Meaning |
|---|---|
| `no_river` | the object is not under `<river>/` |
| `no_captured_at` | no metadata and no timestamp in the name |
| `rejected_qc` | unreadable, unsupported format, too small, too much nodata, or truncated beyond 20% |
| `no_bounds` | it has findings but nowhere to place them; an empty report would hide them |
| `storage` | GCS read or crop write failed |
| `backend_<status>` / `backend_unreachable` | the backend refused the report or could not be reached |

## Delivery semantics

| Backend answer | Job behaviour |
|---|---|
| 201 (new) / 200 (duplicate) | done; the answer's `duplicate` / `alerted` flags are counted in the summary |
| network error, timeout (30 s), 408, 429, 5xx | retried up to 4 attempts with exponential backoff (2, 4, 8 s) |
| 401 | the ID token is minted again once, then retried |
| other 4xx | not retried; counted as `backend_<status>` |

The backend deduplicates by `Idempotency-Key`, so re-running a prefix never creates duplicates or new
alerts. Because the key has no model version, a newer model re-processing the same image generation is
seen as a duplicate.

The backend alerts only for `confidence >= 0.5` on scenes captured within the last 7 days; older or weaker
detections are stored and mapped without alerting.
