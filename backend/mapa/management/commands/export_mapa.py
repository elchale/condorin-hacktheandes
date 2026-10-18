"""Prints the public map payload (the same JSON as GET /api/v1/mapa) for the offline snapshot.

    python -X utf8 manage.py export_mapa > ../mapa-data/mapa-snapshot.json

Read only: it never writes to the database.
"""
import json

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder

from mapa.builder import build_mapa


class Command(BaseCommand):
    help = 'Print the public map payload as JSON (contract A).'

    def add_arguments(self, parser):
        parser.add_argument('--compact', action='store_true', help='No indentation.')

    def handle(self, *args, **options):
        indent = None if options['compact'] else 2
        self.stdout.write(json.dumps(build_mapa(), cls=DjangoJSONEncoder, ensure_ascii=False, indent=indent))
