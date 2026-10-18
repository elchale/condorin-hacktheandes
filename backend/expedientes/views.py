"""The expediente page talks to these two routes, authenticated by the token in the WhatsApp link.

GET    /api/v1/expedientes/<token>              open (creates and prefills it on the first tap)
GET    /api/v1/expedientes/<token>?formato=pdf  the PDF: final once confirmed, BORRADOR before
PATCH  /api/v1/expedientes/<token>              autosave fields, record filings, reopen
POST   /api/v1/expedientes/<token>/enviar       {} sends the WhatsApp code; {"code"} finalizes and emails it
"""
from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.whatsapp import WhatsAppError

from . import codes, mailer
from .autodraft import adopt
from .models import Expediente
from .pdf import build_pdf
from .serializers import ExpedienteUpdateSerializer, event_payload, expediente_payload
from .services import alert_for_token, finalize, missing_fields, open_expediente, update_expediente


def _open(alert):
    """The expediente behind a link; an automatic draft is found, never created twice."""
    return adopt(open_expediente(alert), alert.member)


class ExpedienteView(APIView):
    throttle_scope = 'expediente'

    def get(self, request, token):
        alert = alert_for_token(token)
        expediente = _open(alert)
        if request.query_params.get('formato') == 'pdf':
            return _pdf_response(expediente)
        return Response(expediente_payload(expediente, alert))

    def patch(self, request, token):
        alert = alert_for_token(token)
        expediente = _open(alert)
        serializer = ExpedienteUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        expediente = update_expediente(expediente, alert.member, dict(serializer.validated_data))
        return Response(expediente_payload(expediente, alert))


class EventoView(APIView):
    """GET /api/v1/eventos/<token>: the event page. Read only, so it never opens the expediente."""

    throttle_scope = 'expediente'

    def get(self, request, token):
        return Response(event_payload(alert_for_token(token)))


class ExpedienteSendView(APIView):
    throttle_scope = 'expediente_send'

    def post(self, request, token):
        alert = alert_for_token(token)
        expediente = _open(alert)
        member = alert.member

        if expediente.status != Expediente.Status.DRAFT:
            raise ValidationError({'status': ['Este expediente ya fue confirmado.']})
        missing = missing_fields(expediente)
        if missing:
            raise ValidationError({field: [message] for field, message in missing.items()})

        code = str(request.data.get('code', '')).strip()
        if not code:
            try:
                codes.send_code(expediente, member)
            except WhatsAppError:
                return Response({'message': 'No pudimos enviar el código por WhatsApp. Intenta de nuevo.',
                                 'type': 'whatsapp_error', 'field_errors': {}},
                                status=status.HTTP_502_BAD_GATEWAY)
            return Response({'status': 'code_sent', 'phone_hint': codes.phone_hint(member.phone),
                             'expires_in': codes.CODE_MINUTES * 60}, status=status.HTTP_202_ACCEPTED)

        codes.check_code(expediente, member, code)
        expediente = finalize(expediente, member)
        emailed = mailer.send_to_ong(expediente, member)
        authorities_emailed = mailer.send_to_authorities(expediente)
        payload = expediente_payload(expediente, alert)
        payload['sent'] = {'emailed_to': emailed, 'authorities_emailed': authorities_emailed}
        return Response(payload)


def _pdf_response(expediente: Expediente) -> HttpResponse:
    final = expediente.status != Expediente.Status.DRAFT and expediente.pdf
    content = bytes(expediente.pdf) if final else build_pdf(expediente, final=False)
    filename = f'{expediente.folio}.pdf' if final else f'borrador-{expediente.pk}.pdf'
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    response['Cache-Control'] = 'no-store'
    return response
