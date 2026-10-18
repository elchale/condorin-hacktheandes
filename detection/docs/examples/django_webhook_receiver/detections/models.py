from django.db import models


class DetectionEvent(models.Model):
    """One webhook delivery = one image generation. Deduplicated on the Idempotency-Key header."""

    idempotency_key = models.CharField(max_length=1024, unique=True)
    bucket = models.CharField(max_length=255)
    object = models.CharField(max_length=1024)
    generation = models.CharField(max_length=64)
    river = models.CharField(max_length=255, null=True, blank=True)
    satellite = models.CharField(max_length=255, null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    model_name = models.CharField(max_length=255)
    model_version = models.CharField(max_length=255)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return self.idempotency_key


class Detection(models.Model):
    event = models.ForeignKey(DetectionEvent, related_name="detections", on_delete=models.CASCADE)
    lat = models.FloatField(null=True)
    lon = models.FloatField(null=True)
    confidence = models.FloatField()
    bbox = models.JSONField()  # [x, y, w, h] in full-image pixels, top-left origin
    crop_uri = models.CharField(max_length=2048)


class ReviewTask(models.Model):
    """Human review for low-confidence detections. Verdicts become new training labels."""

    class Verdict(models.TextChoices):
        PENDING = "pending"
        MINING_VESSEL = "mining_vessel"
        OTHER_VESSEL = "other_vessel"
        NO_VESSEL = "no_vessel"

    detection = models.OneToOneField(Detection, related_name="review", on_delete=models.CASCADE)
    verdict = models.CharField(max_length=32, choices=Verdict.choices, default=Verdict.PENDING)
    reviewer = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
