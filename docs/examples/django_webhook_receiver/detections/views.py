"""POST /api/v1/detections: authenticate, dedupe on Idempotency-Key, store, enqueue, answer fast."""

import hmac
import json

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Detection, DetectionEvent
from .tasks import process_detection_event


def _authorized(request) -> bool:
    expected = getattr(settings, "CONDORIN_WEBHOOK_TOKEN", "")
    header = request.headers.get("Authorization", "")
    if not expected or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer ") :].encode(), expected.encode())


@csrf_exempt
@require_POST
def detections_webhook(request):
    if not _authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    key = request.headers.get("Idempotency-Key")
    if not key:
        return JsonResponse({"error": "missing Idempotency-Key"}, status=400)
    try:
        body = json.loads(request.body)
        image, model = body["image"], body["model"]
        detections = body["detections"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "invalid body"}, status=400)

    if DetectionEvent.objects.filter(idempotency_key=key).exists():
        return JsonResponse({"status": "duplicate"}, status=200)  # at-least-once delivery
    try:
        with transaction.atomic():
            event = DetectionEvent.objects.create(
                idempotency_key=key,
                bucket=image["bucket"],
                object=image["object"],
                generation=image["generation"],
                river=image.get("river"),
                satellite=image.get("satellite"),
                captured_at=parse_datetime(image["captured_at"]) if image.get("captured_at") else None,
                model_name=model["name"],
                model_version=model["version"],
                payload=body,
            )
            Detection.objects.bulk_create(
                Detection(event=event, lat=d.get("lat"), lon=d.get("lon"),
                          confidence=d["confidence"], bbox=d["bbox"], crop_uri=d["crop_uri"])
                for d in detections
            )
    except IntegrityError:  # a concurrent delivery of the same key won the race
        return JsonResponse({"status": "duplicate"}, status=200)
    except (KeyError, TypeError):
        return JsonResponse({"error": "invalid body"}, status=400)

    transaction.on_commit(lambda: process_detection_event.delay(event.pk))
    return JsonResponse({"status": "accepted", "id": event.pk}, status=200)
