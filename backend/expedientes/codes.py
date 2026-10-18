"""A WhatsApp code confirms that whoever finalizes the expediente holds the member's phone.

The link alone can be forwarded; the code cannot, so a forwarded link can read and edit
the draft but never sign it in the ONG's name.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core import whatsapp
from core.exceptions import BaseError

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 45


class CodeInvalid(BaseError):
    default_detail = 'El código no es correcto.'


class CodeExpired(BaseError):
    default_detail = 'El código venció. Te enviamos uno nuevo si lo pides otra vez.'


class CodeTooSoon(BaseError):
    status_code = 429
    default_detail = 'Espera unos segundos antes de pedir otro código.'


def _digest(expediente_id: int, member_id: int, code: str) -> str:
    message = f'{expediente_id}:{member_id}:{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def send_code(expediente, member) -> None:
    now = timezone.now()
    if (expediente.code_hash and expediente.code_member_id == member.pk and expediente.code_expires_at
            and expediente.code_expires_at - timedelta(minutes=CODE_MINUTES) + timedelta(seconds=RESEND_SECONDS) > now):
        raise CodeTooSoon()

    code = f'{secrets.randbelow(10 ** 6):06d}'
    whatsapp.send_code(member.phone, code)
    expediente.code_hash = _digest(expediente.pk, member.pk, code)
    expediente.code_member = member
    expediente.code_expires_at = now + timedelta(minutes=CODE_MINUTES)
    expediente.code_attempts = 0
    expediente.save(update_fields=['code_hash', 'code_member', 'code_expires_at', 'code_attempts', 'updated'])


def check_code(expediente, member, code: str) -> None:
    """Raises unless `code` is the live code sent to this member. Clears it once used."""
    if not expediente.code_hash or expediente.code_member_id != member.pk:
        raise CodeExpired('Primero pide el código.')
    if timezone.now() >= expediente.code_expires_at or expediente.code_attempts >= MAX_ATTEMPTS:
        raise CodeExpired()

    expediente.code_attempts += 1
    if not hmac.compare_digest(expediente.code_hash, _digest(expediente.pk, member.pk, code.strip())):
        expediente.save(update_fields=['code_attempts', 'updated'])
        raise CodeInvalid()

    expediente.code_hash, expediente.code_member, expediente.code_expires_at = '', None, None
    expediente.save(update_fields=['code_hash', 'code_member', 'code_expires_at', 'code_attempts', 'updated'])


def phone_hint(phone: str) -> str:
    """'51936282808' → '+51 *** *** 808'"""
    return f'+{phone[:2]} *** *** {phone[-3:]}'
