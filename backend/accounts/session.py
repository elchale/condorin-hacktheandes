"""Signed values for the SPA sign in (contract B): the pending code and the 30 day session.

Both are `django.core.signing.TimestampSigner` values under SECRET_KEY, with their own salt so one can
never be used as the other. Nothing is stored server side except a short lived attempt counter in the
cache. The code itself never leaves the server: the pending value only carries an HMAC of it, keyed
with SECRET_KEY (a bare sha256 of a 6 digit code could be reversed offline in a millisecond).

Caveat: the attempt counter and the 45 s resend lock live in Django's cache. With the default LocMem
cache each instance counts on its own, which is fine on one Cloud Run instance; behind several the
limits are per instance until CACHES points at a shared backend.
"""
import hashlib
import hmac
import re

from django.conf import settings
from django.core import signing
from rest_framework import status

from core.exceptions import BaseError

PENDING_SALT = 'otp-pending'
SESSION_SALT = 'session'
CODE_SECONDS = 10 * 60
SESSION_SECONDS = 30 * 24 * 60 * 60
# A WhatsApp alert link is easier to pass on than a code, so its session is shorter (like condorin.pe).
LINK_SESSION_SECONDS = 7 * 24 * 60 * 60

# How the session was opened. A `link` session never finalizes an expediente: that always asks for a
# fresh WhatsApp code (expedientes.codes), whatever the session.
VIA_CODE = 'code'
VIA_LINK = 'link'

PHONE_RE = re.compile(r'^\d{10,15}$')


class SessionInvalid(BaseError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Tu sesión venció o no es válida. Vuelve a entrar.'


def normalize_phone(raw) -> str | None:
    """'936 282 808' → '51936282808'. Digits only; 9 digit Peruvian numbers get the 51 prefix."""
    digits = re.sub(r'\D', '', str(raw or ''))
    if len(digits) == 9:
        digits = f'51{digits}'
    return digits if PHONE_RE.match(digits) else None


def code_digest(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f'otp|{phone}|{code}'.encode(), hashlib.sha256).hexdigest()


def pending_value(phone: str, code: str) -> str:
    return signing.TimestampSigner(salt=PENDING_SALT).sign_object({'p': phone, 'h': code_digest(phone, code)})


def read_pending(value: str) -> dict:
    """{'p': phone, 'h': digest}. Raises signing.SignatureExpired or signing.BadSignature."""
    data = signing.TimestampSigner(salt=PENDING_SALT).unsign_object(value, max_age=CODE_SECONDS)
    if not isinstance(data, dict) or not PHONE_RE.match(str(data.get('p', ''))) or not data.get('h'):
        raise signing.BadSignature('malformed pending value')
    return data


def session_token(phone: str, via: str = VIA_CODE) -> str:
    return signing.TimestampSigner(salt=SESSION_SALT).sign_object({'p': phone, 'via': via})


def read_session(token: str) -> tuple[str, str] | None:
    """(phone, via) for a valid session token; None when missing, forged or past its lifetime
    (30 days for a code session, 7 for a link session)."""
    signer = signing.TimestampSigner(salt=SESSION_SALT)
    try:
        data = signer.unsign_object(token, max_age=SESSION_SECONDS)
    except (signing.BadSignature, ValueError):  # SignatureExpired is a BadSignature; ValueError: bad payload
        return None
    if not isinstance(data, dict) or not PHONE_RE.match(str(data.get('p', ''))):
        return None
    via = data.get('via')
    if via == VIA_LINK:
        try:
            signer.unsign_object(token, max_age=LINK_SESSION_SECONDS)
        except signing.SignatureExpired:
            return None
    elif via != VIA_CODE:
        return None
    return data['p'], via


def bearer_session(request) -> tuple[str, str] | None:
    """(phone, via) behind `Authorization: Bearer <session>`, or None when absent or invalid."""
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return None
    return read_session(token.strip())


def bearer_phone(request) -> str | None:
    session = bearer_session(request)
    return session[0] if session else None


def require_session(request, allow_link: bool = True) -> str:
    """The signed in phone. With allow_link=False only a session opened with a WhatsApp code counts."""
    session = bearer_session(request)
    if session is None or (session[1] == VIA_LINK and not allow_link):
        raise SessionInvalid()
    return session[0]
