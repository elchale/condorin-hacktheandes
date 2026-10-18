"""What day it is for the whole API: the real clock, or a demo clock set to any instant.

`now()` replaces `timezone.now()` wherever the product reasons about time: which scenes exist yet
(`visible()` hides the ones captured after now), which scene is recent enough to alert, when an alert
was sent or an expediente opened, and the date printed on the PDF. Security windows (link expiry,
WhatsApp codes, signed sessions) keep the real clock on purpose.

The state is one row (`core.models.Clock`), read through the process cache for a few seconds so a
request costs at most one extra query and every Cloud Run instance follows a change within that time.
Set it with `manage.py set_today 2026-07-10` (or `--real`), or in the admin. Changing the day also
queues and sends the WhatsApp alerts of every scene still recent on that day (`replay_today`): captured
within the alert window before now (detections.limits: ALERT_RECENT_DAYS, or today and yesterday while the
hackathon limit is set), the same window a live webhook delivery alerts on.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta

from django.db import DatabaseError
from django.utils import timezone

from .cache import local as cache
from .models import Clock

logger = logging.getLogger(__name__)

CACHE_KEY = 'clock:state:v1'
CACHE_SECONDS = 5

DAYS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
          'noviembre', 'diciembre']


def _state() -> tuple[datetime | None, datetime | None]:
    """(demo_at, set_at) of the clock row; (None, None) in real time or when the table is unreachable."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        row = Clock.objects.filter(pk=1).values_list('demo_at', 'set_at').first()
    except DatabaseError:
        logger.warning('clock: could not read the clock row, using the real time')
        return None, None
    state = (row[0], row[1]) if row and row[0] and row[1] else (None, None)
    cache.set(CACHE_KEY, state, CACHE_SECONDS)
    return state


def now() -> datetime:
    """The API's current instant (aware, UTC): the real one, or the demo one still ticking."""
    real = timezone.now()
    demo_at, set_at = _state()
    if demo_at is None:
        return real
    return demo_at + (real - set_at)


def today() -> date:
    return timezone.localdate(now())


def is_simulated() -> bool:
    return _state()[0] is not None


def visible(queryset, field: str = 'captured_at'):
    """Only the rows dated up to now: with the demo clock, what has "already happened"."""
    return queryset.filter(**{f'{field}__lte': now()})


def iso(value: datetime | None) -> str | None:
    """ISO 8601 in UTC to the second, with Z: '2026-10-18T03:00:00Z'. None stays None."""
    if value is None:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def label(value: datetime | None = None) -> str:
    """'viernes 10 de julio de 2026', in Lima time."""
    local = timezone.localtime(value or now())
    return f'{DAYS[local.weekday()]} {local.day} de {MONTHS[local.month - 1]} de {local.year}'


def payload() -> dict:
    """The block the panel and the map show: `{"now", "today", "label", "simulated", "timezone"}`."""
    current = now()
    return {
        'now': iso(current),
        'today': timezone.localdate(current).isoformat(),
        'label': label(current),
        'simulated': is_simulated(),
        'timezone': timezone.get_current_timezone_name(),
    }


def parse(value: str) -> datetime:
    """'2026-07-10' (that day at the current Lima time of day) or '2026-07-10T09:00' (Lima), as an aware instant."""
    text = value.strip()
    tz = timezone.get_current_timezone()
    if len(text) == 10:
        day = date.fromisoformat(text)
        local_now = timezone.localtime()
        return datetime.combine(day, local_now.time().replace(microsecond=0), tzinfo=tz)
    parsed = datetime.fromisoformat(text)
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def set_demo(value: datetime | date | str | None, note: str = '') -> Clock:
    """Moves the clock to `value` (None returns to real time) and forgets the cached state."""
    if isinstance(value, str):
        value = parse(value)
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = parse(value.isoformat())
    if value is not None and timezone.is_naive(value):
        value = timezone.make_aware(value)
    row, _ = Clock.objects.get_or_create(pk=1)
    row.demo_at = value
    row.set_at = timezone.now() if value is not None else None
    row.note = note[:200]
    row.save()
    cache.delete(CACHE_KEY)
    return row


def day_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    """[start, end) of a Lima calendar day as aware instants."""
    day = day or today()
    tz = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def recent_scenes():
    """The scenes still recent now (captured within the alert window, up to now) that have something to
    alert about, oldest first: today's scene and the ones of the days just before it."""
    from detections.limits import window_start
    from detections.models import SatelliteImage
    from detections.services import is_simulated as scene_is_simulated

    current = now()
    start = window_start(current)
    scenes = (SatelliteImage.objects.select_related('river')
              .filter(captured_at__gte=start, captured_at__lte=current).order_by('captured_at'))
    return [s for s in scenes if s.alerting_detections().exists() and not scene_is_simulated(s)]


def replay_today(send: bool = True) -> list[dict]:
    """Queues the alerts of the recent scenes for every recipient who has none yet and, with `send`, sends them.

    Idempotent: an alert row is unique per (image, member) and only pending or failed ones are sent, so
    running it twice, or after a real delivery, never messages anyone twice. Returns one row per scene.
    """
    from detections.models import Alert
    from detections.services import process_image, queue_alerts

    rows = []
    for image in recent_scenes():
        queued = queue_alerts(image)
        if send:
            process_image(image.pk)
        alerts = Alert.objects.filter(image=image)
        rows.append({
            'image': image,
            'queued': queued,
            'sent': alerts.filter(status=Alert.Status.SENT).count(),
            'failed': alerts.filter(status=Alert.Status.FAILED).count(),
            'pending': alerts.filter(status=Alert.Status.PENDING).count(),
        })
    return rows
