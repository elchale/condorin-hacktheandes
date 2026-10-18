# Example Django receiver (reference only)

A minimal reference for the Django team's `POST /api/v1/detections` endpoint. It is **not** part of the
`condorin` package and is not deployed from this repo.

- `models.py`: `DetectionEvent` (unique `idempotency_key`), `Detection` rows, and `ReviewTask` for human review.
- `views.py`: CSRF-exempt POST; constant-time bearer check (`hmac.compare_digest`) → 401; requires
  `Idempotency-Key` → 400; stores once; duplicates return **200**; heavy work goes to Celery after commit.
- `tasks.py`: Celery task. Low-confidence detections create a `ReviewTask`; reviewer verdicts become new
  training labels (feedback loop).
- `tests.py`: valid token, missing/wrong token, missing key, duplicate delivery, invalid body.

Run the tests (needs only `django`):

```bash
pip install "django>=5.0,<6"
cd docs/examples/django_webhook_receiver && python runtests.py
```

Settings used: `CONDORIN_WEBHOOK_TOKEN` (from your secret store, never committed) and
`CONDORIN_REVIEW_BELOW` (detections below this confidence go to human review).

Note: a migration is not included; run `makemigrations detections` in your project.
