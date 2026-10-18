import json

from django.test import TestCase, override_settings

from .models import Detection, DetectionEvent, ReviewTask

TOKEN = "test-token-not-real"
KEY = "river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"
# Exactly the body the condorin notifier sends (Appendix B1)
BODY = {
    "image": {
        "bucket": "river-images",
        "object": "yaguas/2026-10-15T1042Z_s1.jpeg",
        "generation": "1792297654023751",
        "river": "yaguas",
        "satellite": "Skyfi",
        "captured_at": "2026-10-15T10:42:00Z",
    },
    "model": {"name": "dredge-detector", "version": "v0.3"},
    "detections": [
        {"lat": -2.7706, "lon": -70.9512, "confidence": 0.87, "bbox": [412, 318, 14, 9],
         "crop_uri": "gs://river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"},
        {"lat": -2.7710, "lon": -70.9515, "confidence": 0.30, "bbox": [500, 300, 30, 12],
         "crop_uri": "gs://river-images/yaguas/2026-10-15T1042Z_s1.jpeg#1792297654023751"},
    ],
}
URL = "/api/v1/detections"


@override_settings(CONDORIN_WEBHOOK_TOKEN=TOKEN, CONDORIN_REVIEW_BELOW=0.62)
class WebhookTests(TestCase):
    def post(self, token=TOKEN, key=KEY, body=BODY):
        headers = {}
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(URL, data=json.dumps(body), content_type="application/json",
                                    **headers)

    def test_valid_delivery(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        ev = DetectionEvent.objects.get(idempotency_key=KEY)
        self.assertEqual((ev.river, ev.model_version), ("yaguas", "v0.3"))
        self.assertEqual(Detection.objects.count(), 2)
        self.assertTrue(DetectionEvent.objects.get().processed)
        self.assertEqual(ReviewTask.objects.count(), 1)  # the 0.30 detection

    def test_missing_or_wrong_token(self):
        self.assertEqual(self.post(token=None).status_code, 401)
        self.assertEqual(self.post(token="wrong").status_code, 401)
        self.assertEqual(DetectionEvent.objects.count(), 0)

    def test_missing_idempotency_key(self):
        self.assertEqual(self.post(key=None).status_code, 400)

    def test_duplicate_delivery_is_200_without_second_row(self):
        self.assertEqual(self.post().status_code, 200)
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "duplicate")
        self.assertEqual(DetectionEvent.objects.count(), 1)
        self.assertEqual(Detection.objects.count(), 2)

    def test_invalid_body(self):
        self.assertEqual(self.post(body={"image": {}}).status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)
