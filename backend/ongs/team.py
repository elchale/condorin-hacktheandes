"""The hidden internal ONG "Equipo Ojo de Cóndor": the condorin.pe admins as alert recipients.

It watches every river and holds, as members, the active admins (`accounts_admin`) that have a
WhatsApp phone. Being a regular ONG, the alert, the personal token and the expediente work for the
admins exactly as for any ONG member. `internal=True` keeps it out of the public map and the panel.
"""
from django.db import transaction

from accounts.models import Admin

from .models import Member, Ong, River

TEAM_NAME = 'Equipo Ojo de Cóndor'


def internal_team() -> Ong:
    team = Ong.objects.filter(internal=True).order_by('pk').first()
    if team is None:
        team = Ong.objects.create(name=TEAM_NAME, short_name=TEAM_NAME, internal=True)
    return team


@transaction.atomic
def sync_internal_team() -> Ong:
    """Makes the team watch every river and mirror the admins with a phone. Idempotent and cheap."""
    team = internal_team()
    team.rivers.add(*River.objects.exclude(ongs=team))

    phones = {}
    for admin in Admin.objects.filter(active=True).exclude(phone__isnull=True).exclude(phone=''):
        phones.setdefault(admin.phone, admin.name or admin.email.split('@')[0])
    for phone, name in phones.items():
        member, created = Member.objects.get_or_create(ong=team, phone=phone, defaults={'full_name': name})
        if not created and not member.active:
            member.active = True
            member.save(update_fields=['active', 'updated'])
    team.members.filter(active=True).exclude(phone__in=phones).update(active=False)
    return team
