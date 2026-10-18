"""Move the API's clock to a day (and send that day's alerts), show it, or return to real time.

    manage.py set_today                       what day it is for the API right now
    manage.py set_today 2026-07-10            that day, at the current Lima time of day; sends the recent alerts
    manage.py set_today 2026-07-10T09:00      that exact instant (Lima time); the clock ticks on from there
    manage.py set_today --real                back to the real clock
    manage.py set_today 2026-07-10 --no-send  move the day but queue nothing and send nothing
    manage.py set_today --resend              send again the recent alerts that are still pending or failed

Every member of every ONG that watches the river gets the WhatsApp of every scene still recent on that day
(captured within ALERT_RECENT_DAYS before the clock's now, as a live delivery would), once:
alerts are unique per (image, member), so repeating the command never messages anyone twice.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import clock


class Command(BaseCommand):
    help = 'Set the day the API lives in (demo clock) and send the alerts of the scenes recent on that day.'

    def add_arguments(self, parser):
        parser.add_argument('when', nargs='?', help='2026-07-10 or 2026-07-10T09:00 (Lima time).')
        parser.add_argument('--real', action='store_true', help='Return to the real clock.')
        parser.add_argument('--no-send', action='store_true', help='Move the clock without sending any alert.')
        parser.add_argument('--resend', action='store_true', help='Only send the pending or failed alerts of today.')
        parser.add_argument('--note', default='', help='Why, for the admin.')

    def handle(self, *args, when, real, no_send, resend, note, **options):
        if real:
            clock.set_demo(None)
            self.stdout.write(self.style.SUCCESS(f'Back to real time: {self._status()}'))
            return
        if when:
            try:
                instant = clock.parse(when)
            except ValueError as exc:
                raise CommandError(f'Could not read "{when}": use 2026-07-10 or 2026-07-10T09:00.') from exc
            clock.set_demo(instant, note=note)
            self.stdout.write(self.style.SUCCESS(f'Clock set: {self._status()}'))
            if no_send:
                self.stdout.write('Nothing queued or sent (--no-send).')
                return
        elif not resend:
            self.stdout.write(self._status())
            return

        rows = clock.replay_today(send=True)
        if not rows:
            self.stdout.write(f'No scene with alerting detections captured in the {settings.ALERT_RECENT_DAYS} days '
                              f'up to {clock.today()}.')
            return
        for r in rows:
            image = r['image']
            self.stdout.write(f'Scene {image.pk} {image.river.slug} {image.satellite} '
                              f'{timezone.localtime(image.captured_at):%Y-%m-%d %H:%M}: '
                              f'{r["queued"]} queued, {r["sent"]} sent, {r["failed"]} failed, {r["pending"]} pending')

    def _status(self) -> str:
        p = clock.payload()
        return (f'today is {p["label"]} ({p["today"]}), {timezone.localtime(clock.now()):%H:%M:%S} Lima, '
                f'{"simulated" if p["simulated"] else "real"}')
