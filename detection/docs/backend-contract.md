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

### Ground resolution (GSD)

The model is sensitive to ground resolution. When the object has custom metadata `gsd_m` (metres per
pixel) and the model card sets `qc.expected_gsd_m`, QC rejects scenes more than `gsd_tolerance` (25%) away.
Without `gsd_m` the check is skipped and the task's summary counts the scene in `gsd_unchecked`.

## When a scene is **not** reported

Posting would be wrong in these cases, so the image is skipped and counted as failed (the execution exits
non-zero). Reason codes appear in the logs and in `failures_by_reason`:

| Reason | Meaning |
|---|---|
| `no_river` | the object is not under `<river>/` |
| `no_captured_at` | no metadata and no timestamp in the name |
| `rejected_qc` | unreadable, unsupported format, too small, too much nodata, truncated beyond 20%, or GSD mismatch (the detail names it) |
| `bad_gsd_m` | custom metadata `gsd_m` is not a positive number |
| `no_bounds` | it has findings but nowhere to place them; an empty report would hide them |
| `storage` | GCS read or crop write failed |
| `backend_<status>` / `backend_unreachable` | the backend refused the report or could not be reached |
| `not_started` | the task reached its time budget (5 min before its timeout) first; a re-run picks it up |
| `jev_unavailable` | Jev could not confirm the scene's strong detections (after retries, or the key/request was refused) |

Each task writes every one of these to `gs://<bucket>/reports/<execution>/task-NNN.json`
(`not_reported`: object, reason, detail), next to its summary.

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

The backend alerts only for `confidence >= 0.5` (`ALERT_MIN_CONFIDENCE`) on scenes captured within the last
7 days; older or weaker detections are stored and mapped without alerting. With the Jev validator on, every
reported detection at or above 0.5 has been confirmed by Jev (below).

## Final validation (TypeSafe Jev)

Code: `src/condorin/job/validator.py`. Turned on by `JEV_ENABLED=true` (set by `deploy/gcp-setup.sh` when
the `typesafe-api-key` secret exists).

**Which detections.** Positive-class detections with confidence ≥ `JEV_TRIGGER_CONFIDENCE` (0.5, the
backend's alert level), at most `JEV_MAX_CANDIDATES` (20) per scene, strongest first; candidates beyond
the cap are not sent and are not reported. Weaker detections skip Jev and are reported as before.

**Request** (one per scene; [API reference](https://docs.typesafe.ai/api), [images](https://docs.typesafe.ai/images)):

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <TYPESAFE_API_KEY>
TypeSafe-Danger-Zone-Images: true            # required for any request carrying an image
Content-Type: multipart/form-data; boundary=… (part "request" = JSON body, one PNG part per crop)
```

```json
{
  "model": "jev-1.13.0",
  "state": {
    "context": "Each crop is an overhead satellite image (about 0.5 m per pixel) of a river in the Peruvian Amazon, …",
    "candidates": [{"crop": "crop-<uuid>"}, {"crop": "crop-<uuid>"}]
  },
  "assets": {"crop-<uuid>": {"type": "image", "part": "image-0", "format": "png"}, "…": {}},
  "questions": {
    "candidate_0": {
      "type": "noul",
      "instructions": "Is the object at the centre of `candidates[0].crop` an illegal-mining dredge or mining barge?",
      "criteria": {"true": "A mining dredge or barge: …", "false": "Not a dredge or barge: a small boat or canoe, a log, …"}
    }
  }
}
```

- Each crop is a 384 px square of the full-resolution scene centred on the detection, shifted to stay
  inside the image, upscaled ×2 to 768 px (the API accepts 280-1568 px per side; full 2560 px scenes are
  too large). A fresh UUID reference per crop, as the docs recommend.
- The model is pinned to `jev-1.13.0`: the `jev-latest` alias moves, and the 0.7 threshold is tuned
  against one version. The response's `model` field is logged with the token `usage`.

**Decision.** `answers.candidate_<i>.noul` is the probability of "yes" (a Noul has no separate
confidence). A candidate is confirmed when `noul >= JEV_MIN_NOUL` (0.7, inclusive). Rejected candidates
are dropped from the backend payload; if all are rejected the scene is reported with the remaining
weaker detections, or `[]`. Each task's report lists them under `jev_rejections` (object, confidence,
noul, box, reason `below_min_noul` or `not_checked`), and the summary counts `jev_confirmed` /
`jev_rejected`.

**Errors.** Like the official SDK: 408, 429 and 5xx (`529` = overloaded) are retried up to
`JEV_MAX_RETRIES` (3) times with exponential backoff (0.5 s doubling, max 5 s, 25% jitter), honouring
`Retry-After` / `retry-after-ms` (capped at 60 s); connection errors and timeouts (`JEV_TIMEOUT_S`, 60 s)
are retried too. 400, 401, 413, 415 and 422 are not retried. If Jev cannot answer, the scene is **not
reported** (`jev_unavailable`): a strong detection is never sent unconfirmed. The key is never logged.

Images are a "Dreamer-ready" (beta) feature of the TypeSafe API: the format, limits and accuracy can change
between releases. Check a key and the request format with `scripts/check_jev.py`.
