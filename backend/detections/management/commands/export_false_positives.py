"""Prints what ONGs rejected as "No es una draga", as hard negatives for the next training run.

    python manage.py export_false_positives > false_positives.json

One row per rejected scene and ONG, with the crops the model proposed (pinned GCS URIs), its confidence and
the reason the ONG gave. Read only: it never writes to the database.
"""
import json

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder

from detections.models import Triage


class Command(BaseCommand):
    help = 'Print the incidents ONGs rejected as not a dredge, as JSON.'

    def add_arguments(self, parser):
        parser.add_argument('--compact', action='store_true', help='No indentation.')

    def handle(self, *args, **options):
        rows = []
        triages = (Triage.objects.filter(status=Triage.Status.FALSE_POSITIVE)
                   .select_related('image__river', 'ong').prefetch_related('image__detections').order_by('updated'))
        for triage in triages:
            image = triage.image
            rows.append({
                'image': image.gs_uri,
                'river': image.river.slug,
                'captured_at': image.captured_at,
                'model': f'{image.model_name} {image.model_version}',
                'ong': triage.ong.display_name,
                'reason': triage.reason,
                'rejected_at': triage.updated,
                'detections': [
                    {'index': d.index, 'confidence': d.confidence, 'bbox': d.bbox, 'crop': d.crop_uri,
                     'crop_sha256': d.crop_sha256}
                    for d in image.detections.all()
                ],
            })
        indent = None if options['compact'] else 2
        self.stdout.write(json.dumps(rows, cls=DjangoJSONEncoder, ensure_ascii=False, indent=indent))
