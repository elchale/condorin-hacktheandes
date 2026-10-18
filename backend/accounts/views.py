"""Sign in for the map SPA (contract B): a WhatsApp code, then a Bearer session token.

POST  /api/v1/auth/codigo                         {"phone", "consent": true} → 202 {"phone", "pending"}
POST  /api/v1/auth/entrar                         {"pending", "code"} → {"token", "member", "ong", "via": "code"}
POST  /api/v1/auth/enlace                         {"token": <alert token>} → the same with "via": "link" (7 days)
GET   /api/v1/me?page=N                           Bearer → the GET /api/v1/panel payload, one page of incidents
                                                  plus {"pagination": {"count", "next", "previous"}}
GET   /api/v1/me/incidentes?page=N                Bearer → {"count", "next", "previous", "results"} ("Ver más")
POST  /api/v1/me/incidentes/<id>/expediente       Bearer → {"token"} (the member's expediente link)

Browsers call these directly (the static SPA at condorin.pe and the map). A `link` session reads the panel
and opens expedientes like any other, but finalizing a denuncia still needs the WhatsApp code sent to
that member's phone (POST /api/v1/expedientes/<token>/enviar), so a forwarded link never signs anything.
"""
import hashlib
import hmac
import logging
import secrets

from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core import whatsapp
from core.exceptions import BaseError
from expedientes.codes import MAX_ATTEMPTS, RESEND_SECONDS, CodeExpired, CodeInvalid, CodeTooSoon
from panel.services import incident_images, member_for_phone, open_from_panel, sign_in_by_link, with_expedientes
from panel.views import IncidentPagination, incident_rows, panel_payload

from .models import Member as SiteUser
from .session import (
    CODE_SECONDS,
    VIA_CODE,
    VIA_LINK,
    code_digest,
    normalize_phone,
    pending_value,
    read_pending,
    require_session,
    session_token,
)

logger = logging.getLogger(__name__)


class WhatsappError(BaseError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = 'No pudimos enviar el código por WhatsApp. Intenta de nuevo en un momento.'


def _attempts_key(pending: str) -> str:
    return f'otp-attempts:{hashlib.sha256(pending.encode()).hexdigest()[:40]}'


def record_sign_in(phone: str) -> bool:
    """Upserts accounts_member like condorin.pe does (src/lib/members.ts). True when the row is new."""
    now = timezone.now()
    try:
        with transaction.atomic():
            _, created = SiteUser.objects.update_or_create(
                phone=phone, defaults={'consent_at': now, 'last_sign_in_at': now})
    except IntegrityError:  # two sign ins racing for the same new number
        SiteUser.objects.filter(phone=phone).update(consent_at=now, last_sign_in_at=now, updated=now)
        created = False
    return created


class CodeView(APIView):
    throttle_scope = 'auth_code'

    def post(self, request):
        phone = normalize_phone(request.data.get('phone'))
        if phone is None:
            raise ValidationError({'phone': ['Escribe tu número de WhatsApp, por ejemplo 936282808.']})
        if request.data.get('consent') is not True:
            raise ValidationError({'consent': ['Necesitamos que aceptes los términos para continuar.']})

        lock = f'otp-sent:{phone}'
        if not cache.add(lock, 1, RESEND_SECONDS):
            raise CodeTooSoon()
        code = f'{secrets.randbelow(10 ** 6):06d}'
        try:
            whatsapp.send_code(phone, code)
        except whatsapp.WhatsAppError as exc:
            cache.delete(lock)
            logger.warning('sign in code to %s failed: %s', phone[-3:], exc)
            raise WhatsappError() from exc
        return Response({'phone': phone, 'pending': pending_value(phone, code), 'expires_in': CODE_SECONDS},
                        status=status.HTTP_202_ACCEPTED)


class EnterView(APIView):
    throttle_scope = 'auth_enter'

    def post(self, request):
        pending = str(request.data.get('pending', '')).strip()
        code = str(request.data.get('code', '')).strip()
        if not pending:
            raise ValidationError({'pending': ['Primero pide el código.']})
        if not (code.isdigit() and len(code) == 6):
            raise ValidationError({'code': ['El código tiene 6 dígitos.']})
        try:
            data = read_pending(pending)
        except signing.SignatureExpired as exc:
            raise CodeExpired() from exc
        except signing.BadSignature as exc:
            raise CodeExpired('Primero pide el código.') from exc

        key = _attempts_key(pending)
        cache.add(key, 0, CODE_SECONDS)
        try:
            attempts = cache.incr(key)
        except ValueError:  # evicted between add and incr
            cache.set(key, 1, CODE_SECONDS)
            attempts = 1
        if attempts > MAX_ATTEMPTS:
            raise CodeExpired('Hiciste demasiados intentos. Pide un código nuevo.')

        phone = data['p']
        if not hmac.compare_digest(data['h'], code_digest(phone, code)):
            raise CodeInvalid()
        cache.set(key, MAX_ATTEMPTS, CODE_SECONDS)  # used: the same pending value never signs in twice

        record_sign_in(phone)
        member, _ = member_for_phone(phone)
        return Response(_signed_in(member, VIA_CODE))


class LinkEnterView(APIView):
    """Signs in from the "Crear expediente" button of a WhatsApp alert, under the rules of sign_in_by_link:
    only alerts WhatsApp delivered, within LINK_SIGN_IN_DAYS; anything else gets the same 404."""
    throttle_scope = 'panel_link'

    def post(self, request):
        member = sign_in_by_link(str(request.data.get('token', '')).strip())
        return Response(_signed_in(member, VIA_LINK))


def _signed_in(member, via: str) -> dict:
    return {
        'token': session_token(member.phone, via),
        'via': via,
        'member': {'name': member.full_name, 'phone': member.phone},
        'ong': {'name': member.ong.display_name},
    }


class MeView(APIView):
    throttle_scope = 'me'

    def get(self, request):
        member, joined = member_for_phone(require_session(request))
        paginator = IncidentPagination()
        page = paginator.paginate_queryset(incident_images(member.ong), request, view=self)
        payload = panel_payload(member, joined, with_expedientes(member.ong, page))
        payload['pagination'] = {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
        }
        return Response(payload)


class MeIncidentsView(APIView):
    """The next pages of the member's incidents, in DRF's standard page envelope."""
    throttle_scope = 'me'

    def get(self, request):
        member, _ = member_for_phone(require_session(request))
        paginator = IncidentPagination()
        page = paginator.paginate_queryset(incident_images(member.ong), request, view=self)
        return paginator.get_paginated_response(incident_rows(with_expedientes(member.ong, page)))


class MeExpedienteView(APIView):
    throttle_scope = 'me'

    def post(self, request, image_id):
        member, _ = member_for_phone(require_session(request))
        return Response({'token': open_from_panel(member, image_id).token})
