"""Load the Admin and Member rows saved from the old Prisma tables into the Django ones.

The backup is a JSON file {"tables": {"Admin": [...], "Member": [...]}} taken before the
database was handed over to Django. It is kept outside the repo because it holds phone numbers.
"""
import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Admin, Member


def _dt(value: str) -> datetime:
    # Prisma stored naive UTC timestamps.
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class Command(BaseCommand):
    help = 'Import admins and members from a JSON backup of the old Prisma tables.'

    def add_arguments(self, parser):
        parser.add_argument('path')

    @transaction.atomic
    def handle(self, *args, path, **options):
        tables = json.load(open(path, encoding='utf-8'))['tables']
        for row in tables.get('Admin', []):
            admin, _ = Admin.objects.update_or_create(
                email=row['email'].lower(), defaults={'name': row.get('name'), 'active': row.get('active', True)},
            )
            Admin.objects.filter(pk=admin.pk).update(created=_dt(row['createdAt']))
        for row in tables.get('Member', []):
            member, _ = Member.objects.update_or_create(
                phone=row['phone'],
                defaults={'consent_at': _dt(row['consentAt']), 'last_sign_in_at': _dt(row['lastSignInAt'])},
            )
            Member.objects.filter(pk=member.pk).update(created=_dt(row['createdAt']), updated=_dt(row['updatedAt']))
        self.stdout.write(f'{Admin.objects.count()} admins, {Member.objects.count()} members.')
