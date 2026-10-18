"""The GET /api/v1/fuentes payload, served from FeedCache with stale while revalidate.

A request never waits on an upstream: it reads the cached rows and, for each row past its TTL, starts
one background refresh thread (the same thread pattern as `detections.services.dispatch`; there is no
task queue). Two guards stop a stampede: a process lock with the set of sources being refreshed here,
and the `refreshing_since` column, claimed with one conditional UPDATE so only one instance of the
service refreshes a source at a time (a claim older than five minutes is taken over). A failed fetch
keeps the last good payload, records the error and leaves the claim in place, which backs the
source off for those five minutes. `manage.py refresh_fuentes` and `POST /api/v1/fuentes/refresh`
(called every 30 minutes by the refresh-feeds GitHub workflow) run the same refresh synchronously, so
visitors normally find every source fresh and the background thread is only the fallback.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from core.clock import iso
from ongs.models import River

from . import summary
from .http import Meter
from .models import FeedCache
from .sources import REGISTRY, TILE_LAYERS

logger = logging.getLogger(__name__)

CLAIM_TIMEOUT = timedelta(minutes=5)
NEXT_PASSES = 3
REFRESH_WAIT_S = 45

_lock = threading.Lock()
_running: set[str] = set()


def is_stale(row: FeedCache | None, now=None) -> bool:
    if row is None or row.fetched_at is None:
        return True
    return (now or timezone.now()) - row.fetched_at >= timedelta(seconds=row.ttl_s)


def claim(source_id: str, force: bool = False) -> bool:
    """Mark the source as refreshing; False when another worker already holds a fresh claim."""
    module = REGISTRY[source_id]
    FeedCache.objects.get_or_create(source=source_id, defaults={'ttl_s': module.TTL_S})
    now = timezone.now()
    rows = FeedCache.objects.filter(source=source_id)
    if not force:
        rows = rows.filter(Q(refreshing_since__isnull=True) | Q(refreshing_since__lt=now - CLAIM_TIMEOUT))
    return rows.update(refreshing_since=now) == 1


def refresh(source_id: str, force: bool = False) -> FeedCache | None:
    """Fetch one source now and store the result. Returns the row, or None when someone else holds it."""
    if not claim(source_id, force=force):
        return None
    module = REGISTRY[source_id]
    meter, started = Meter(), time.monotonic()
    try:
        data = module.fetch(meter=meter)
    except Exception as exc:
        ms = int((time.monotonic() - started) * 1000)
        logger.warning('fuentes: %s failed after %d ms (%s bytes): %r', source_id, ms, meter.bytes, exc)
        # Keep payload and fetched_at; the claim stays, so the next try waits CLAIM_TIMEOUT.
        FeedCache.objects.filter(source=source_id).update(
            ok=False, error=f'{exc.__class__.__name__}: {exc}'[:500], ttl_s=module.TTL_S,
            duration_ms=ms, bytes_in=meter.bytes, refreshing_since=timezone.now())
        return FeedCache.objects.get(source=source_id)
    ms = int((time.monotonic() - started) * 1000)
    warnings = data.pop('warnings', None) or []
    FeedCache.objects.filter(source=source_id).update(
        payload=data, fetched_at=timezone.now(), ok=True, error='; '.join(warnings)[:500],
        ttl_s=module.TTL_S, duration_ms=ms, bytes_in=meter.bytes, refreshing_since=None)
    logger.info('fuentes: %s refreshed in %d ms, %s bytes in, %d warnings', source_id, ms, meter.bytes, len(warnings))
    return FeedCache.objects.get(source=source_id)


def _run(source_id: str, in_thread: bool = True) -> None:
    try:
        refresh(source_id)
    except Exception:
        logger.exception('fuentes: refresh of %s crashed', source_id)
    finally:
        with _lock:
            _running.discard(source_id)
        if in_thread:
            close_old_connections()


def schedule_refresh(source_id: str) -> bool:
    """Start one background refresh for the source unless this process already runs one."""
    with _lock:
        if source_id in _running:
            return False
        _running.add(source_id)
    if getattr(settings, 'FUENTES_INLINE', False):
        _run(source_id, in_thread=False)
    else:
        threading.Thread(target=_run, args=(source_id,), daemon=True, name=f'fuentes-{source_id}').start()
    return True


def _refresh_in_thread(source_id: str, force: bool) -> FeedCache | None:
    try:
        return refresh(source_id, force=force)
    finally:
        close_old_connections()


def _status(row: FeedCache | None) -> dict:
    if row is None:
        return {'status': 'busy'}
    return {'status': 'ok' if row.ok else 'failed', 'fetched_at': iso(row.fetched_at),
            'duration_ms': row.duration_ms, 'error': row.error or None}


def refresh_due(force: bool = False, wait_s: float = REFRESH_WAIT_S) -> dict:
    """Refresh every stale source (every source with force) now, all at once on their own threads.

    Returns {source: {status, ...}} where status is ok, failed, fresh (skipped), busy (another worker
    holds the claim) or running (still going after wait_s; it finishes in the background, which keeps
    the request under the 60 s Cloud Run and gunicorn timeouts).
    """
    rows = {row.source: row for row in FeedCache.objects.filter(source__in=REGISTRY)}
    out, due = {}, []
    for source_id in REGISTRY:
        if force or is_stale(rows.get(source_id)):
            due.append(source_id)
        else:
            out[source_id] = {'status': 'fresh', 'fetched_at': iso(rows[source_id].fetched_at)}
    if getattr(settings, 'FUENTES_INLINE', False):  # tests: one thread, one database connection
        for source_id in due:
            out[source_id] = _status(refresh(source_id, force=force))
        return {source_id: out[source_id] for source_id in REGISTRY}
    if due:
        pool = ThreadPoolExecutor(max_workers=len(due), thread_name_prefix='fuentes-refresh')
        futures = {source_id: pool.submit(_refresh_in_thread, source_id, force) for source_id in due}
        wait(futures.values(), timeout=wait_s)
        pool.shutdown(wait=False)
        for source_id, future in futures.items():
            if not future.done():
                out[source_id] = {'status': 'running'}
            elif future.exception() is not None:
                out[source_id] = {'status': 'failed', 'error': future.exception().__class__.__name__}
            else:
                out[source_id] = _status(future.result())
    return {source_id: out[source_id] for source_id in REGISTRY}


def upcoming_passes(satellite: dict, now) -> dict:
    """The satellite dict with `next_passes` cut to the next NEXT_PASSES still in the future."""
    cutoff = iso(now)
    out = {}
    for slug, entry in satellite.items():
        if 'next_passes' in entry:
            entry = {**entry, 'next_passes': [p for p in entry['next_passes'] if p['at'] > cutoff][:NEXT_PASSES]}
        out[slug] = entry
    return out


def get_payload(revalidate: bool = True) -> dict:
    rows = {row.source: row for row in FeedCache.objects.filter(source__in=REGISTRY)}
    now = timezone.now()
    sources = {}
    for source_id, module in REGISTRY.items():
        row = rows.get(source_id)
        if revalidate and is_stale(row, now) and not _claimed_recently(row, now):
            schedule_refresh(source_id)
        sources[source_id] = {
            'fetched_at': iso(row.fetched_at) if row else None,
            'ok': bool(row and row.ok),
            'ttl_s': module.TTL_S,
            'error': (row.error or None) if row else 'pendiente',
            'attribution': module.ATTRIBUTION,
            'url': module.URL,
        }

    def data(source_id):
        row = rows.get(source_id)
        return row.payload if row and row.fetched_at else {}

    satellite = upcoming_passes(data('sentinel').get('rivers') or {}, now)
    weather = data('open-meteo').get('rivers') or {}
    rivers = data('glofas').get('rivers') or {}
    near = data('firms').get('near_rivers') or {}
    slugs = set(satellite) | set(weather) | set(rivers) | set(near)
    names = dict(River.objects.filter(slug__in=slugs).values_list('slug', 'name')) if slugs else {}
    return {
        'generated_at': iso(now),
        'sources': sources,
        'fires': data('firms').get('fires') or {'type': 'FeatureCollection', 'features': []},
        'satellite': satellite,
        'weather': weather,
        'tile_layers': TILE_LAYERS,
        'rivers': rivers,
        'fires_near_rivers': near,
        'summary': summary.build(slugs, names, weather, rivers, satellite, near),
    }


def _claimed_recently(row: FeedCache | None, now) -> bool:
    """Skip the thread entirely when another instance holds a live claim (saves a write per request)."""
    return bool(row and row.refreshing_since and now - row.refreshing_since < CLAIM_TIMEOUT)
