"""Retry alerts that are still pending, failed or abandoned mid send (run it from a cron, or by hand after an outage)."""
from django.core.management.base import BaseCommand

from detections.models import Alert
from detections.services import process_image, retriable


class Command(BaseCommand):
    help = 'Send every pending or failed WhatsApp alert that has attempts left.'

    def handle(self, *args, **options):
        # Pending, failed, or left `sending` by a process that died mid send (ALERT_SENDING_STALE_MINUTES).
        image_ids = retriable(Alert.objects.all()).values_list('image_id', flat=True).distinct()
        for image_id in image_ids:
            process_image(image_id)
        sent = Alert.objects.filter(image_id__in=list(image_ids), status=Alert.Status.SENT).count()
        self.stdout.write(f'{len(image_ids)} images processed, {sent} alerts now sent.')
