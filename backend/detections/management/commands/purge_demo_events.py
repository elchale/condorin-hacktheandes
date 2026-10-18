"""List, and with --yes delete, the demo and mock scenes with their detections, alerts and expedientes.

A scene counts as demo when any of these holds:
- its payload is marked `simulated` or `demo` (simulate_detection marks its own);
- it is one of the PlanetScope demo scenes (Planet 2016/2017 images stored under `escenas/` with
  simulated 2026 dates);
- every detection in it is the sample detection of the tests and of simulate_detection
  (the point -2.7706, -70.9512 with the bbox [412, 318, 14, 9]), i.e. a mock delivery.

ONGs, members, rivers and admins are kept.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from detections.models import Alert, Detection, SatelliteImage
from detections.services import is_simulated
from expedientes.models import Expediente

SAMPLE_POINT = (-2.7706, -70.9512)
SAMPLE_BBOX = [412, 318, 14, 9]


def demo_reason(image: SatelliteImage) -> str | None:
    if is_simulated(image):
        return 'marked simulated or demo'
    if image.satellite.lower() == 'planetscope' and image.object_name.startswith('escenas/'):
        return 'PlanetScope demo scene'
    detections = list(image.detections.all())
    if detections and all(
        (round(float(d.lat), 4), round(float(d.lon), 4)) == SAMPLE_POINT and list(d.bbox) == SAMPLE_BBOX
        for d in detections
    ):
        return 'sample detection (mock delivery)'
    return None


class Command(BaseCommand):
    help = 'List the demo scenes; with --yes delete them with their detections, alerts and expedientes.'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Actually delete them.')

    def handle(self, *args, yes, **options):
        demo = []
        for image in SatelliteImage.objects.select_related('river').prefetch_related('detections').order_by('pk'):
            reason = demo_reason(image)
            if reason:
                demo.append(image.pk)
                self.stdout.write(f'{image.pk:>5} {image.river.slug:<12} {image.satellite:<12} '
                                  f'{timezone.localtime(image.captured_at):%Y-%m-%d %H:%M}  {reason}')

        counts = {
            'images': len(demo),
            'detections': Detection.objects.filter(image_id__in=demo).count(),
            'alerts': Alert.objects.filter(image_id__in=demo).count(),
            'expedientes': Expediente.objects.filter(image_id__in=demo).count(),
        }
        kept = SatelliteImage.objects.exclude(pk__in=demo).count()
        summary = ', '.join(f'{v} {k}' for k, v in counts.items())
        if not yes:
            self.stdout.write(f'Would delete {summary}. {kept} scenes stay. Pass --yes to delete.')
            return
        with transaction.atomic():
            # Expediente.image is PROTECT; its filings cascade. Detections and alerts cascade with the image.
            Expediente.objects.filter(image_id__in=demo).delete()
            SatelliteImage.objects.filter(pk__in=demo).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {summary}. {kept} scenes stay.'))
