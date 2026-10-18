"""Give a condorin.pe admin a WhatsApp phone, so they receive every recent alert of every river.

    python manage.py set_admin_phone admin@example.org 51987654321
    python manage.py set_admin_phone admin@example.org --clear

Then syncs the hidden internal ONG (ongs.team) that holds the admins as alert recipients.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Admin
from core.phone import phone_validator
from ongs.team import sync_internal_team


class Command(BaseCommand):
    help = 'Set (or --clear) the WhatsApp phone of an admin, digits with country code.'

    def add_arguments(self, parser):
        parser.add_argument('email')
        parser.add_argument('phone', nargs='?', default='')
        parser.add_argument('--clear', action='store_true')

    def handle(self, *args, email, phone, clear, **options):
        admin = Admin.objects.filter(email=email.strip().lower()).first()
        if admin is None:
            raise CommandError(f'No admin with email {email}.')
        if clear:
            admin.phone = None
        else:
            phone = ''.join(ch for ch in phone if ch.isdigit())
            try:
                phone_validator(phone)
            except ValidationError as exc:
                raise CommandError(exc.messages[0]) from exc
            admin.phone = phone
        admin.save(update_fields=['phone'])
        team = sync_internal_team()
        recipients = team.members.filter(active=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'{admin.email}: phone {"cleared" if clear else "set"}. {team} has {recipients} active admin recipients.'))
