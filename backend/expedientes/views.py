"""The expediente page talks to these two routes, authenticated by the token in the WhatsApp link.

GET    /api/v1/expedientes/<token>              open (creates and prefills it on the first tap)
GET    /api/v1/expedientes/<token>?formato=pdf  the PDF: final once confirmed, BORRADOR before
PATCH  /api/v1/expedientes/<token>              autosave fields, record filings, reopen (filings also need
                                                Authorization: Bearer <a code session of that member>)
POST   /api/v1/expedientes/<token>/enviar       {} sends the WhatsApp code; {"code"} finalizes and emails it
GET    /api/v1/expedientes/<token>/notas        the member's field notes for this river (Atomic Memory, optional;
POST   /api/v1/expedientes/<token>/notas        {"text"} saves one; both need a code session of that member)
PATCH  /api/v1/expedientes/<token>/notas/<id>   {"text"} corrects one; DELETE removes it
"""
from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.session import VIA_CODE, bearer_session
from core.exceptions import BaseError
from core.whatsapp import WhatsAppError

from . import codes, mailer, notas
from .autodraft import adopt
from .models import Expediente
from .pdf import build_pdf
from .serializers import ExpedienteUpdateSerializer, event_payload, expediente_payload
from .services import (
    alert_for_token,
    existing_expediente,
    finalize,
    missing_fields,
    open_expediente,
    require_can_act,
    update_expediente,
)


class CodeSessionRequired(BaseError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = ('Para registrar la presentación ante una autoridad, entra con el código que te enviamos '
                      'por WhatsApp y vuelve a intentarlo.')


def require_code_session(request, member) -> None:
    """Recording a filing says the ONG filed the denuncia: the link alone (forwardable) is not enough, it takes a
    session opened with a WhatsApp code sent to this same member."""
    session = bearer_session(request)
    if session is None or session[1] != VIA_CODE or session[0] != member.phone:
        raise CodeSessionRequired()


class NotesSessionRequired(BaseError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'Tus notas de campo son personales. Entra con el código que te enviamos por WhatsApp para verlas.'


class NotesUnavailable(BaseError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'No pudimos llegar a tus notas ahora. La nota no se guardó; el expediente sigue igual.'


class NotesDisabled(BaseError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Las notas de campo no están activadas.'


def notes_member(request, alert):
    """Whose notes these are: the member of the link, and only with their own code session, since a link can be
    forwarded and the notes follow the person across incidents. The memory subject comes from that member row."""
    require_can_act(alert.member)
    session = bearer_session(request)
    if session is None or session[1] != VIA_CODE or session[0] != alert.member.phone:
        raise NotesSessionRequired()
    return alert.member


def _note_text(request) -> str:
    """The note exactly as sent (ends trimmed): a non string, empty or too long note is a 400, never cut."""
    try:
        return notas.valid_text(request.data.get('text') if isinstance(request.data, dict) else None)
    except notas.InvalidNote as exc:
        raise ValidationError({'text': [str(exc)]}) from None


def _open(alert):
    """The expediente behind a link; an automatic draft is found, never created twice."""
    require_can_act(alert.member)
    return adopt(open_expediente(alert), alert.member)


class ExpedienteView(APIView):
    throttle_scope = 'expediente'

    def get(self, request, token):
        alert = alert_for_token(token)
        if not alert.member.can_act:
            # An observer reads the ONG's draft, without the signer's data; the PDF carries it, so it stays closed.
            if request.query_params.get('formato') == 'pdf':
                require_can_act(alert.member)
            return Response(expediente_payload(existing_expediente(alert), alert))
        expediente = _open(alert)
        if request.query_params.get('formato') == 'pdf':
            return _pdf_response(expediente)
        return Response(expediente_payload(expediente, alert))

    def patch(self, request, token):
        alert = alert_for_token(token)
        expediente = _open(alert)
        serializer = ExpedienteUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get('filings'):
            require_code_session(request, alert.member)
        expediente = update_expediente(expediente, alert.member, dict(serializer.validated_data))
        return Response(expediente_payload(expediente, alert))


class EventoView(APIView):
    """GET /api/v1/eventos/<token>: the event page. Read only, so it never opens the expediente."""

    throttle_scope = 'expediente'

    def get(self, request, token):
        return Response(event_payload(alert_for_token(token)))


class NotasView(APIView):
    """The member's field notes beside the form. Reference for the person only: never part of the denuncia."""

    throttle_scope = 'expediente'

    def get(self, request, token):
        alert = alert_for_token(token)
        if not notas.enabled():
            # Only says the feature is off; no note is read, so no session is needed for this answer.
            return Response({'enabled': False, 'notes': []})
        member = notes_member(request, alert)
        place = (Expediente.objects.filter(image=alert.image, ong=member.ong)
                 .values_list('place_reference', flat=True).first() or '')
        try:
            found = notas.relevant(member, alert.image.river, place)
        except notas.MemoryUnavailable:
            raise NotesUnavailable('No pudimos cargar tus notas ahora. El expediente sigue igual.') from None
        return Response({'enabled': True, 'notes': [n.as_dict() for n in found]})

    def post(self, request, token):
        alert = alert_for_token(token)
        if not notas.enabled():
            raise NotesDisabled()
        member = notes_member(request, alert)
        text = _note_text(request)
        expediente_id = (Expediente.objects.filter(image=alert.image, ong=member.ong)
                         .values_list('pk', flat=True).first())
        try:
            note = notas.save(member, alert.image.river, text, expediente_id)
        except notas.MemoryUnavailable:
            raise NotesUnavailable() from None
        return Response({'note': note.as_dict()}, status=status.HTTP_201_CREATED)


class NotaView(APIView):
    throttle_scope = 'expediente'

    def _member(self, request, token):
        alert = alert_for_token(token)
        if not notas.enabled():
            raise NotesDisabled()
        return notes_member(request, alert)

    def patch(self, request, token, note_id):
        member = self._member(request, token)
        text = _note_text(request)
        try:
            note, previous_deleted = notas.correct(member, note_id, text)
        except notas.NoteNotFound:
            raise NotFound('No encontramos esa nota.') from None
        except notas.MemoryUnavailable:
            raise NotesUnavailable('No pudimos guardar la corrección. Tu nota sigue como estaba.') from None
        return Response({'note': note.as_dict(), 'previous_deleted': previous_deleted})

    def delete(self, request, token, note_id):
        member = self._member(request, token)
        try:
            notas.delete(member, note_id)
        except notas.NoteNotFound:
            raise NotFound('No encontramos esa nota.') from None
        except notas.MemoryUnavailable:
            raise NotesUnavailable('No pudimos borrar la nota ahora. Sigue guardada; intenta de nuevo.') from None
        return Response({'deleted': True})


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
