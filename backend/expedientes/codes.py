"""A WhatsApp code confirms that whoever finalizes the expediente holds the member's phone.

The link alone can be forwarded; the code cannot, so a forwarded link can read and edit
the draft but never sign it in the ONG's name.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core import whatsapp
from core.exceptions import BaseError

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 45
# Each new code resets the attempts, so new codes are capped too: at most this many per expediente per hour.
MAX_SENDS_PER_HOUR = 5


class CodeInvalid(BaseError):
    default_detail = 'El código no es correcto.'


class CodeExpired(BaseError):
    default_detail = 'El código venció. Te enviamos uno nuevo si lo pides otra vez.'


class CodeTooSoon(BaseError):
    status_code = 429
    default_detail = 'Espera unos segundos antes de pedir otro código.'


class CodeLimit(BaseError):
    status_code = 429
    default_detail = 'Pediste demasiados códigos para este expediente. Intenta de nuevo en una hora.'


def _digest(expediente_id: int, member_id: int, code: str) -> str:
    message = f'{expediente_id}:{member_id}:{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def send_code(expediente, member) -> None:
    """Stores a new code for this member and sends it. The row is locked while the code is chosen, so two
    requests at once cannot both pass the 45 s and hourly limits; WhatsApp is called after the commit."""
    from .models import Expediente

    now = timezone.now()
    code = f'{secrets.randbelow(10 ** 6):06d}'
    digest = _digest(expediente.pk, member.pk, code)
    with transaction.atomic():
        row = Expediente.objects.select_for_update().get(pk=expediente.pk)
        if (row.code_hash and row.code_member_id == member.pk and row.code_expires_at
                and row.code_expires_at - timedelta(minutes=CODE_MINUTES) + timedelta(seconds=RESEND_SECONDS) > now):
            raise CodeTooSoon()
        if row.code_sends_since is None or now - row.code_sends_since >= timedelta(hours=1):
            row.code_sends, row.code_sends_since = 0, now
        if row.code_sends >= MAX_SENDS_PER_HOUR:
            raise CodeLimit()
        row.code_sends += 1
        row.code_hash, row.code_member, row.code_expires_at, row.code_attempts = (
            digest, member, now + timedelta(minutes=CODE_MINUTES), 0)
        row.save(update_fields=['code_hash', 'code_member', 'code_expires_at', 'code_attempts',
                                'code_sends', 'code_sends_since', 'updated'])
    try:
        whatsapp.send_code(member.phone, code)
    except whatsapp.WhatsAppError:
        # Not delivered: drop it so the member may ask again at once (it still counts toward the hour).
        Expediente.objects.filter(pk=expediente.pk, code_hash=digest).update(
            code_hash='', code_member=None, code_expires_at=None)
        raise
    for field in ('code_hash', 'code_member_id', 'code_expires_at', 'code_attempts', 'code_sends',
                  'code_sends_since'):
        setattr(expediente, field, getattr(row, field))


def check_code(expediente, member, code: str) -> None:
    """Raises unless `code` is the live code sent to this member. Clears it once used.

    Every attempt is counted with one conditional UPDATE (attempts below MAX_ATTEMPTS), so parallel guesses
    cannot go past the limit, and the code is cleared the same way, so it is used at most once.
    """
    from .models import Expediente

    current = Expediente.objects.filter(pk=expediente.pk).values(
        'code_hash', 'code_member_id', 'code_expires_at').first() or {}
    digest = current.get('code_hash')
    if not digest or current.get('code_member_id') != member.pk:
        raise CodeExpired('Primero pide el código.')
    live = Expediente.objects.filter(pk=expediente.pk, code_hash=digest, code_member_id=member.pk,
                                     code_expires_at__gt=timezone.now())
    if not live.filter(code_attempts__lt=MAX_ATTEMPTS).update(code_attempts=F('code_attempts') + 1):
        raise CodeExpired()
    if not hmac.compare_digest(digest, _digest(expediente.pk, member.pk, code.strip())):
        raise CodeInvalid()
    if not live.update(code_hash='', code_member=None, code_expires_at=None):
        raise CodeExpired()  # another request used it a moment ago
    # The caller saves the whole row next (finalize), so it must carry what the database holds now.
    expediente.refresh_from_db(fields=['code_hash', 'code_member', 'code_expires_at', 'code_attempts',
                                       'code_sends', 'code_sends_since'])


def phone_hint(phone: str) -> str:
    """'51936282808' → '+51 *** *** 808'"""
    return f'+{phone[:2]} *** *** {phone[-3:]}'
