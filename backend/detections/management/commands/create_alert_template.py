"""Submit the alert (WA_ALERT_TEMPLATE, `condorin_evento_v2`) UTILITY template to Meta for review.

Meta needs a sample image for an IMAGE header, uploaded through the Resumable Upload API of
the app that owns the token. Without --submit it only prints what it would send.
"""
import json
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from detections.text import alert_template_definition

SAMPLE = Path(settings.BASE_DIR) / 'static' / 'brand' / 'alerta-ejemplo.jpg'


class Command(BaseCommand):
    help = 'Create the WhatsApp alert template on the WABA (needs WA_TOKEN and WA_WABA_ID).'

    def add_arguments(self, parser):
        parser.add_argument('--submit', action='store_true', help='Actually send it to Meta.')

    def handle(self, *args, submit, **options):
        if not submit:
            self.stdout.write(json.dumps(alert_template_definition('<header_handle>'), indent=2, ensure_ascii=False))
            self.stdout.write('\nDry run. Pass --submit to send it to Meta.')
            return
        if not (settings.WA_TOKEN and settings.WA_WABA_ID):
            raise CommandError('WA_TOKEN and WA_WABA_ID are required.')

        handle = self._upload_sample()
        res = requests.post(
            f'{settings.WA_GRAPH_URL}/{settings.WA_WABA_ID}/message_templates',
            json=alert_template_definition(handle),
            headers=self._auth(), timeout=30,
        )
        if not res.ok:
            raise CommandError(f'Meta rejected the template: {res.status_code} {res.text}')
        self.stdout.write(self.style.SUCCESS(f'Submitted: {res.json()}'))

    def _auth(self):
        return {'Authorization': f'Bearer {settings.WA_TOKEN}'}

    def _upload_sample(self) -> str:
        app = requests.get(f'{settings.WA_GRAPH_URL}/app', headers=self._auth(), timeout=15)
        if not app.ok:
            raise CommandError(f'Could not read the app of the token: {app.text}')
        data = SAMPLE.read_bytes()
        session = requests.post(
            f"{settings.WA_GRAPH_URL}/{app.json()['id']}/uploads",
            params={'file_name': SAMPLE.name, 'file_length': len(data), 'file_type': 'image/jpeg'},
            headers=self._auth(), timeout=15,
        )
        if not session.ok:
            raise CommandError(f'Could not open an upload session: {session.text}')
        upload = requests.post(
            f"{settings.WA_GRAPH_URL}/{session.json()['id']}",
            data=data, headers={'Authorization': f'OAuth {settings.WA_TOKEN}', 'file_offset': '0'}, timeout=60,
        )
        if not upload.ok:
            raise CommandError(f'Could not upload the sample image: {upload.text}')
        return upload.json()['h']
