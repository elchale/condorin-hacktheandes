"""Refresh the open data feeds now (warm up after a deploy, or a scheduled job).

    python -X utf8 manage.py refresh_fuentes                 # every stale source
    python -X utf8 manage.py refresh_fuentes --force         # every source, even fresh or claimed
    python -X utf8 manage.py refresh_fuentes --source firms  # one source

Writes only FeedCache rows.
"""
from django.core.management.base import BaseCommand, CommandError

from fuentes.models import FeedCache
from fuentes.services import is_stale, refresh
from fuentes.sources import REGISTRY


class Command(BaseCommand):
    help = 'Fetch the live open data feeds (FIRMS, Sentinel, Open-Meteo) into FeedCache.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=sorted(REGISTRY), help='Only this source.')
        parser.add_argument('--force', action='store_true', help='Refresh even if fresh or claimed by a worker.')

    def handle(self, *args, source=None, force=False, **options):
        failed = 0
        for source_id in [source] if source else list(REGISTRY):
            row = FeedCache.objects.filter(source=source_id).first()
            if not force and not is_stale(row):
                self.stdout.write(f'{source_id}: fresh (fetched {row.fetched_at:%Y-%m-%d %H:%M}Z), skipped')
                continue
            row = refresh(source_id, force=force)
            if row is None:
                self.stdout.write(f'{source_id}: another worker is refreshing it, skipped (use --force)')
                continue
            failed += not row.ok
            self.stdout.write(f'{source_id}: {"ok" if row.ok else "FAILED"} in {row.duration_ms} ms, '
                              f'{row.bytes_in} bytes in, {_summary(source_id, row.payload)}'
                              + (f', error: {row.error}' if row.error else ''))
        if failed:
            raise CommandError(f'{failed} source(s) failed')


def _summary(source_id: str, payload: dict) -> str:
    if source_id == 'firms':
        return f"{len((payload.get('fires') or {}).get('features', []))} fires kept of {payload.get('in_bbox', 0)} in bbox"
    rivers = payload.get('rivers') or {}
    return f'{len(rivers)} rivers'
