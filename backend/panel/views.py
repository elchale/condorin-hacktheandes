"""Routes the condorin.pe server calls for the ONG panel and the WhatsApp link sign in.

GET   /api/v1/panel                                  the member, their ONG and its incidents
POST  /api/v1/panel/incidentes/<id>/expediente       the member's link to that incident's expediente
POST  /api/v1/panel/enlace  {"token"}                which member a WhatsApp alert link signs in
GET   /api/v1/panel/actividad?limit=N                the admin live feed: every scene and each decision taken

Every call carries `Authorization: Bearer <PANEL_API_SECRET>`; the first two also `X-Condorin-Phone`.
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock
from core.geo import coord, maps_url, utm
from detections.text import fecha_larga
from expedientes.autodraft import status_label
from expedientes.drafting import place_sentence

from .activity import activity_feed, parse_limit
from .auth import authenticate_frontend, member_phone
from .services import (
    crop_url,
    incident_totals,
    incidents,
    member_for_phone,
    missing_count,
    open_from_panel,
    sign_in_by_link,
)

# How many crops of one scene the panel card shows.
CARD_CROPS = 4


class IncidentPagination(PageNumberPagination):
    """`?page=N` (and optionally `?page_size=N`, up to 50) over the panel incidents, newest first."""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class FrontendView(APIView):
    throttle_scope = 'panel'

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        authenticate_frontend(request)


def _incident(image, detections, expediente, viewer=None) -> dict:
    best = detections[0]
    lat, lon = coord(best.lat), coord(best.lon)
    return {
        'id': image.pk,
        'river': {'slug': image.river.slug, 'name': image.river.name, 'protected_area': image.river.protected_area},
        'place': place_sentence(image.river),
        'satellite': image.satellite,
        'captured_at': image.captured_at,
        'captured_at_label': fecha_larga(image.captured_at),
        'model': f'{image.model_name} {image.model_version}',
        'detections': len(detections),
        'top_confidence': round(best.confidence, 3),
        'lat': lat,
        'lon': lon,
        'utm': utm(float(best.lat), float(best.lon))['label'],
        'maps_url': maps_url(lat, lon),
        'crops': [url for url in (crop_url(d) for d in detections[:CARD_CROPS]) if url],
        'evidence_pinned': bool(image.md5_hash),
        'expediente': expediente and {
            'status': expediente.status,
            'status_label': status_label(expediente),
            'auto_created': expediente.auto_created,
            'reviewed': expediente.updated_by_id is not None,
            'folio': expediente.folio,
            'updated_at': expediente.updated,
            # An observer sees that someone is working on it, never who.
            'updated_by': expediente.updated_by.full_name if expediente.updated_by and (
                viewer is None or viewer.can_act) else None,
            'missing': missing_count(expediente) if expediente.status == expediente.Status.DRAFT else 0,
            'authorities': [a.name for a in expediente.authorities.all()],
            'filings': len(expediente.filings.all()),
        },
    }


def incident_rows(rows, viewer=None) -> list[dict]:
    return [_incident(*row, viewer=viewer) for row in rows]


def panel_payload(member, joined: bool, rows=None) -> dict:
    """What the panel shows a member: shared by GET /api/v1/panel and the SPA's GET /api/v1/me.

    `rows` is one page of incidents (the SPA pages them); without it, the newest INCIDENT_LIMIT. The totals
    always count every incident of the ONG.
    """
    ong = member.ong
    return {
        'clock': clock.payload(),
        'member': {'name': member.full_name, 'phone': member.phone, 'joined_now': joined, 'role': member.role,
                   'can_act': member.can_act},
        'ong': {
            'name': ong.display_name,
            'rivers': [{'slug': r.slug, 'name': r.name, 'protected_area': r.protected_area}
                       for r in ong.rivers.all()],
            'members': ong.members.filter(active=True).count(),
        },
        'totals': incident_totals(ong),
        'incidents': incident_rows(incidents(ong) if rows is None else rows, member),
    }


class PanelView(FrontendView):
    def get(self, request):
        return Response(panel_payload(*member_for_phone(member_phone(request))))


class PanelExpedienteView(FrontendView):
    def post(self, request, image_id):
        member, _ = member_for_phone(member_phone(request))
        alert = open_from_panel(member, image_id)
        return Response({'token': alert.token})


class LinkSignInView(FrontendView):
    throttle_scope = 'panel_link'

    def post(self, request):
        member = sign_in_by_link(str(request.data.get('token', '')).strip())
        return Response({'phone': member.phone, 'name': member.full_name, 'ong': member.ong.display_name})


class ActivityView(FrontendView):
    """Called by the condorin.pe admin server, so the secret alone is enough (no member phone)."""

    def get(self, request):
        return Response(activity_feed(parse_limit(request.query_params.get('limit'))))
