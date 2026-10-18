"""Hackathon safety limits on WhatsApp alerts.

TODO(prod): remove before real production. Hackathon safety limits requested by Carlos on 2026-10-18.
While HACKATHON_ALERT_WINDOW_DAYS is set it overrides the ALERT_RECENT_DAYS setting; set it to None (or
delete this module's use) to go back to the setting. HACKATHON_MAX_ALERT_MESSAGES caps the Alert rows with
status SENT across the whole database (members and admins alike); None removes the cap.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from .models import Alert

# TODO(prod): remove before real production. Hackathon safety limits requested by Carlos on 2026-10-18.
# Only scenes captured today or yesterday (America/Lima calendar days) alert.
HACKATHON_ALERT_WINDOW_DAYS = 2
# Once this many WhatsApp alerts have been sent in total, no further alert goes out.
HACKATHON_MAX_ALERT_MESSAGES = 50
# Only alerts sent from this instant count toward the cap (reset before the live demo). None counts every alert.
HACKATHON_CAP_SINCE = datetime(2026, 10, 18, 7, 50, tzinfo=timezone.get_fixed_timezone(-300))

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


def cap_reached() -> bool:
    cap = HACKATHON_MAX_ALERT_MESSAGES
    return cap is not None and sent_count() >= cap
