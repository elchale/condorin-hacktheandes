"""Send one event (a stored scene) by WhatsApp by hand, to everyone watching its river or to some phones.

A manual send skips the recent window: a person decided to send it. Simulated scenes are still refused.
Without --send it only lists who would get it. Members already sent this event are skipped unless --resend.
"""
from django.core.management.base import BaseCommand, CommandError

from detections.models import Alert, SatelliteImage
from detections.services import is_simulated, pin_evidence, recipients, send_alert_safely
from ongs.models import Member


class Command(BaseCommand):
    help = 'Send the WhatsApp alert of one scene by hand (dry run unless --send).'

    def add_arguments(self, parser):
        parser.add_argument('image_id', type=int, help='SatelliteImage id of the event.')
        parser.add_argument('--phone', action='append', default=[],
                            help='Only this member phone (repeatable). Default: every recipient of the river.')
        parser.add_argument('--send', action='store_true', help='Actually send it.')
        parser.add_argument('--resend', action='store_true', help='Also send to members already sent this event.')

    def handle(self, *args, image_id, phone, send, resend, **options):
        image = SatelliteImage.objects.select_related('river').filter(pk=image_id).first()
        if image is None:
            raise CommandError(f'No scene with id {image_id}.')
        if is_simulated(image):
            raise CommandError(f'Scene {image_id} is simulated: it is never sent.')
        if not image.alerting_detections().exists():
            raise CommandError(f'Scene {image_id} has no detection above ALERT_MIN_CONFIDENCE.')

        if phone:
            members = list(Member.objects.filter(phone__in=phone, active=True, ong__active=True)
                           .select_related('ong').order_by('pk'))
            missing = set(phone) - {m.phone for m in members}
            if missing:
                raise CommandError(f'No active member with phone {", ".join(sorted(missing))}.')
        else:
            members = recipients(image.river)

        self.stdout.write(f'Scene {image.pk}: {image.river.name}, captured {image.captured_at:%Y-%m-%d %H:%M}.')
        if send:
            pin_evidence(image)
        for member in members:
            alert = Alert.objects.filter(image=image, member=member).first()
            label = f'{member.phone} {member.full_name or "(sin nombre)"} [{member.ong.name}]'
            if alert and alert.status == Alert.Status.SENT and not resend:
                self.stdout.write(f'  skip {label}: already sent')
                continue
            if not send:
                self.stdout.write(f'  would send {label}')
                continue
            # A dry run creates nothing: a pending row would be picked up by send_pending_alerts.
            alert = alert or Alert.objects.create(image=image, member=member)
            send_alert_safely(alert, manual=True)
            alert.refresh_from_db()
            self.stdout.write(f'  {alert.status} {label} {alert.error}'.rstrip())
        if not send:
            self.stdout.write('Dry run. Pass --send to send it.')
