"""Run a fake detector delivery through the real pipeline, for local development only.

The payload is marked `"simulated": true`, so the scene is stored but alerts nobody (see
detections.services.is_simulated), and `purge_demo_events` removes it. The command refuses to run
with WA_SEND_ENABLED on: a simulated event must never reach anyone's WhatsApp.
"""
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from detections.serializers import DetectionWebhookSerializer
from detections.services import alert_reason, idempotency_key, ingest


class Command(BaseCommand):
    help = 'Simulate a detector webhook for a river. Stored as simulated: it never sends WhatsApp.'

    def add_arguments(self, parser):
        parser.add_argument('--river', default='yaguas')
        parser.add_argument('--lat', type=float, default=-2.7706)
        parser.add_argument('--lon', type=float, default=-70.9512)
        parser.add_argument('--confidence', type=float, default=0.87)

    def handle(self, *args, river, lat, lon, confidence, **options):
        if settings.WA_SEND_ENABLED:
            raise CommandError('simulate_detection never sends WhatsApp: run it with WA_SEND_ENABLED=False.')
        now = timezone.now()
        generation = str(uuid.uuid4().int)[:16]
        stamp = f'{now:%Y-%m-%dT%H%MZ}'
        raw = {
            'simulated': True,
            'image': {
                'bucket': 'river-images', 'object': f'{river}/{stamp}_s1.tif', 'generation': generation,
                'river': river, 'satellite': 'Sentinel-1', 'captured_at': now.isoformat(),
            },
            'model': {'name': 'dredge-detector', 'version': 'v0.3'},
            'detections': [{
                'lat': lat, 'lon': lon, 'confidence': confidence, 'bbox': [412, 318, 14, 9],
                'crop_uri': f'gs://river-images/crops/{river}_{generation}.png',
            }],
        }
        serializer = DetectionWebhookSerializer(data=raw)
        serializer.is_valid(raise_exception=True)
        image, _ = ingest(serializer.validated_data, f"simulated:{idempotency_key('', raw['image'])}", raw=raw)

        self.stdout.write(f'Image {image.pk}: {image} ({alert_reason(image)}, nobody is alerted)')
        self.stdout.write('Remove it with: python manage.py purge_demo_events --yes')
