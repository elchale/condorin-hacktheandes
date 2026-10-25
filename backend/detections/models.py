"""What the detector reported, and who was alerted about it."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class SatelliteImage(BaseModel):
    """One scene the detector processed. A webhook delivery creates exactly one row.

    `generation` pins the exact version of the object in the bucket, so the evidence
    cannot be swapped later by an overwrite. The hashes come from GCS itself.
    """

    idempotency_key = models.CharField(max_length=512, unique=True)
    river = models.ForeignKey('ongs.River', on_delete=models.PROTECT, related_name='images')
    bucket = models.CharField(max_length=222)
    object_name = models.CharField(max_length=1024)
    generation = models.CharField(max_length=32)
    satellite = models.CharField(max_length=60)
    captured_at = models.DateTimeField()
    model_name = models.CharField(max_length=80)
    model_version = models.CharField(max_length=40)
    # Filled from the bucket metadata when the alert goes out; blank when the bucket is unreachable.
    md5_hash = models.CharField(max_length=64, blank=True)
    crc32c = models.CharField(max_length=16, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    payload = models.JSONField(help_text='Body exactly as received.')

    class Meta:
        ordering = ['-captured_at']
        verbose_name = 'imagen satelital'
        verbose_name_plural = 'imágenes satelitales'

    def __str__(self):
        return f'{self.river} {timezone.localtime(self.captured_at):%Y-%m-%d %H:%M} {self.satellite}'

    @property
    def gs_uri(self):
        return f'gs://{self.bucket}/{self.object_name}#{self.generation}'

    def alerting_detections(self):
        return self.detections.filter(confidence__gte=settings.ALERT_MIN_CONFIDENCE)


class Detection(BaseModel):
    """One object (a dredge, a balsa) the model found in the scene."""

    image = models.ForeignKey(SatelliteImage, on_delete=models.CASCADE, related_name='detections')
    index = models.PositiveSmallIntegerField()
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lon = models.DecimalField(max_digits=9, decimal_places=6)
    confidence = models.FloatField()
    bbox = models.JSONField(help_text='[x, y, width, height] in pixels of the scene.')
    crop_uri = models.CharField(max_length=1024, blank=True)
    # Pinned the same way as the scene once the crop is read from the bucket.
    crop_generation = models.CharField(max_length=32, blank=True)
    crop_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['image', '-confidence']
        constraints = [
            models.UniqueConstraint(fields=['image', 'index'], name='detection_unique_index'),
        ]

    def __str__(self):
        return f'{self.lat}, {self.lon} ({self.confidence:.0%})'


def new_token():
    return secrets.token_urlsafe(24)


def default_expiry():
    return timezone.now() + timedelta(days=settings.ALERT_LINK_DAYS)


def sending_stale_before():
    """An alert still `sending` since before this instant was abandoned and may be claimed again."""
    return timezone.now() - timedelta(minutes=settings.ALERT_SENDING_STALE_MINUTES)


class Alert(BaseModel):
    """The WhatsApp alert one ONG member got about one image.

    `token` goes in the "Crear expediente" button and is the only thing that opens the
    expediente, so it is personal: every member of every ONG gets a different one.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        # Claimed by one sender (thread, instance or command) while WhatsApp answers. A row left here longer
        # than ALERT_SENDING_STALE_MINUTES (the process died mid send) is picked up again by the retries.
        SENDING = 'sending', 'Enviando'
        SENT = 'sent', 'Enviada'
        FAILED = 'failed', 'Falló'
        # Opened from the condorin.pe panel by a member who got no WhatsApp alert; never sent.
        PANEL = 'panel', 'Abierta desde el panel'
        # TODO(prod): hackathon cap (detections/limits.py). Never sent and never retried.
        CAPPED = 'capped', 'No enviada (límite del hackathon)'

    image = models.ForeignKey(SatelliteImage, on_delete=models.CASCADE, related_name='alerts')
    member = models.ForeignKey('ongs.Member', on_delete=models.CASCADE, related_name='alerts')
    token = models.CharField(max_length=64, unique=True, default=new_token)
    expires_at = models.DateTimeField(default=default_expiry)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    wa_message_id = models.CharField(max_length=128, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'alerta'
        constraints = [
            models.UniqueConstraint(fields=['image', 'member'], name='alert_unique_member_per_image'),
        ]

    def __str__(self):
        return f'{self.image} → {self.member}'

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def link(self):
        return f'{settings.FRONTEND_URL}/expediente/{self.token}'


class Triage(BaseModel):
    """What an ONG decided about one scene, shared by all its members. No row means nobody looked yet.

    One per image and ONG, like the expediente. `false_positive` is the ONG saying the model was wrong
    (`reason` says why); those crops are the hard negatives `manage.py export_false_positives` hands to the
    next training run. Nothing is deleted: setting another status undoes a rejection.
    """

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Es una draga'
        FALSE_POSITIVE = 'false_positive', 'No es una draga'
        VERIFIED_FIELD = 'verified_field', 'Verificada en campo'

    class Reason(models.TextChoices):
        BOAT = 'boat', 'Bote o lancha'
        SANDBAR = 'sandbar', 'Banco de arena o sombra'
        OTHER = 'other', 'Otra cosa'

    image = models.ForeignKey(SatelliteImage, on_delete=models.CASCADE, related_name='triages')
    ong = models.ForeignKey('ongs.Ong', on_delete=models.CASCADE, related_name='triages')
    status = models.CharField(max_length=16, choices=Status.choices)
    reason = models.CharField(max_length=10, choices=Reason.choices, blank=True)
    set_by = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        verbose_name = 'triaje'
        verbose_name_plural = 'triajes'
        constraints = [
            models.UniqueConstraint(fields=['image', 'ong'], name='triage_unique_per_image_ong'),
        ]

    def __str__(self):
        return f'{self.ong} {self.image_id}: {self.status}'
