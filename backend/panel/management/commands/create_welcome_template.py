"""Submit the welcome (WA_WELCOME_TEMPLATE, `condorin_bienvenida`) UTILITY template to Meta for review.

Without --submit it only prints what it would send.
"""
import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from panel.welcome import welcome_template_definition


class Command(BaseCommand):
    help = 'Create the WhatsApp welcome template on the WABA (needs WA_TOKEN and WA_WABA_ID).'

    def add_arguments(self, parser):
        parser.add_argument('--submit', action='store_true', help='Actually send it to Meta.')

    def handle(self, *args, submit, **options):
        definition = welcome_template_definition()
        if not submit:
            self.stdout.write(json.dumps(definition, indent=2, ensure_ascii=False))
            self.stdout.write('\nDry run. Pass --submit to send it to Meta.')
            return
        if not (settings.WA_TOKEN and settings.WA_WABA_ID):
            raise CommandError('WA_TOKEN and WA_WABA_ID are required.')
        res = requests.post(
            f'{settings.WA_GRAPH_URL}/{settings.WA_WABA_ID}/message_templates',
            json=definition, headers={'Authorization': f'Bearer {settings.WA_TOKEN}'}, timeout=30,
        )
        if not res.ok:
            raise CommandError(f'Meta rejected the template: {res.status_code} {res.text}')
        self.stdout.write(self.style.SUCCESS(f'Submitted: {res.json()}'))
