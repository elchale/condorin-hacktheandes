"""Hackathon safety limits on WhatsApp alerts.

TODO(prod): remove before real production. Hackathon safety limits requested by Carlos on 2026-10-18.
While HACKATHON_ALERT_WINDOW_DAYS is set it overrides the ALERT_RECENT_DAYS setting; set it to None (or
delete this module's use) to go back to the setting. HACKATHON_MAX_ALERT_MESSAGES caps the Alert rows with
status SENT across the whole database (members and admins alike); None removes the cap.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import Alert, sending_stale_before

# Any 64 bit number, the same in every instance: the Postgres advisory lock that serializes the cap check.
CAP_LOCK_ID = 7_301_018_001


def _since(text: str | None) -> datetime | None:
    if not text:
        return None
    value = datetime.fromisoformat(text)
    return value if timezone.is_aware(value) else timezone.make_aware(value)  # naive: Lima time


# TODO(prod): remove before real production. Hackathon safety limits requested by Carlos on 2026-10-18.
# The values come from the settings (env HACKATHON_ALERT_WINDOW_DAYS, HACKATHON_MAX_ALERT_MESSAGES and
# HACKATHON_CAP_SINCE; 'none' turns one off), read once at import like the constants they replaced.
# Only scenes captured today or yesterday (America/Lima calendar days) alert. Default 2.
HACKATHON_ALERT_WINDOW_DAYS = settings.HACKATHON_ALERT_WINDOW_DAYS
# Once this many WhatsApp alerts have been sent in total, no further alert goes out. Default 150 (raised from 50 for the live pitch signups).
HACKATHON_MAX_ALERT_MESSAGES = settings.HACKATHON_MAX_ALERT_MESSAGES
# Only alerts sent from this instant count toward the cap (reset before the live demo). None counts every alert.
# Default 2026-10-18 07:50 Lima.
HACKATHON_CAP_SINCE = _since(settings.HACKATHON_CAP_SINCE)

CAPPED_ERROR = f'Límite de {HACKATHON_MAX_ALERT_MESSAGES} mensajes del hackathon alcanzado'


def window_start(now: datetime) -> datetime:
    """The earliest capture time that still alerts at `now`.

    With the hackathon window: the start of yesterday in Lima (for 2 days). Without it: ALERT_RECENT_DAYS before now.
    """
    days = HACKATHON_ALERT_WINDOW_DAYS
    if days is None:
        return now - timedelta(days=settings.ALERT_RECENT_DAYS)
    lima = timezone.get_current_timezone()  # TIME_ZONE = 'America/Lima'
    first_day = timezone.localtime(now, lima).date() - timedelta(days=days - 1)
    return datetime.combine(first_day, time.min, tzinfo=lima)


def window_label() -> str:
    days = HACKATHON_ALERT_WINDOW_DAYS
    return f'{settings.ALERT_RECENT_DAYS} days' if days is None else f'{days} Lima days (hackathon limit)'


def sent_count() -> int:
    sent = Alert.objects.filter(status=Alert.Status.SENT)
    if HACKATHON_CAP_SINCE is not None:
        sent = sent.filter(sent_at__gte=HACKATHON_CAP_SINCE)
    return sent.count()


def in_flight_count() -> int:
    """Alerts claimed by a sender right now (status `sending`, not stale): they take a slot of the cap."""
    return Alert.objects.filter(status=Alert.Status.SENDING, updated__gte=sending_stale_before()).count()


def cap_reached(include_in_flight: bool = False) -> bool:
    cap = HACKATHON_MAX_ALERT_MESSAGES
    if cap is None:
        return False
    return sent_count() + (in_flight_count() if include_in_flight else 0) >= cap


def lock_cap() -> None:
    """Serializes the cap check and the claim across threads, instances and commands until the transaction
    ends (pg_advisory_xact_lock, which works behind Neon's transaction pooler). Call it in transaction.atomic."""
    if connection.vendor == 'postgresql':  # the API always runs on Postgres
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [CAP_LOCK_ID])
