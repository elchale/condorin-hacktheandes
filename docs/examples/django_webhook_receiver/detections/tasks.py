"""Heavy work happens here (Celery), never in the webhook request."""

from django.conf import settings

try:
    from celery import shared_task
except ImportError:  # the example runs without Celery: .delay() just calls the function

    def shared_task(fn):
        fn.delay = fn
        return fn


from .models import DetectionEvent, ReviewTask


@shared_task
def process_detection_event(event_id: int) -> None:
    event = DetectionEvent.objects.get(pk=event_id)
    review_below = getattr(settings, "CONDORIN_REVIEW_BELOW", 0.62)  # e.g. the model card's `detect`
    for det in event.detections.all():
        if det.confidence < review_below:
            ReviewTask.objects.get_or_create(detection=det)
        # else: alert / map update / etc.
    event.processed = True
    event.save(update_fields=["processed"])
