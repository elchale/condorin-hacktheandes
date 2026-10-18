"""What the condorin.pe panel shows an ONG member, and the doors into the expediente."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch, QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from core import clock, gcs
from core.exceptions import BaseError
from detections.models import Alert, Detection, SatelliteImage, default_expiry
from expedientes.models import Expediente
from expedientes.services import missing_fields
from ongs.models import Member, Ong

from .welcome import send_welcome

INCIDENT_LIMIT = 50


class NoOngAvailable(BaseError):
    status_code = 503
    default_detail = 'Todavía no hay una ONG para unirte. Escríbenos y te ayudamos.'


def default_ong() -> Ong | None:
    # TODO: demo only. Every new person joins one ONG; replace with real invitations later.
    ongs = Ong.objects.filter(active=True, internal=False)
    if settings.DEFAULT_ONG_ID:
        return ongs.filter(pk=settings.DEFAULT_ONG_ID).first()
    return ongs.order_by('pk').first()


def join_role(phone: str) -> str:
    """An admin (a member of the internal team) joins with full rights; anyone else as DEFAULT_ONG_JOIN_ROLE."""
    if Member.objects.filter(phone=phone, active=True, ong__internal=True).exists():
        return Member.Role.MEMBER
    role = settings.DEFAULT_ONG_JOIN_ROLE
    return role if role in Member.Role.values else Member.Role.OBSERVER


def member_for_phone(phone: str) -> tuple[Member, bool]:
    """The ONG member behind a condorin.pe sign in. Returns (member, joined_now).

    Someone already in an ONG keeps it, with the role they have. Anyone else joins the default ONG (demo only,
    see default_ong) with DEFAULT_ONG_JOIN_ROLE: a full member for the live demo, or an observer who sees the panel
    and gets the alerts but cannot open, edit or sign an expediente of an ONG that never invited them (join_role).
    """
    member = (Member.objects.select_related('ong')
              .filter(phone=phone, active=True, ong__active=True, ong__internal=False).order_by('pk').first())
    if member:
        return member, False
    ong = default_ong()
    if ong is None:
        raise NoOngAvailable()
    # The name is asked in the first expediente ("quién firma") and remembered from there.
    member, created = Member.objects.select_related('ong').get_or_create(
        ong=ong, phone=phone, defaults={'full_name': '', 'role': join_role(phone)},
    )
    if not member.active:
        raise PermissionDenied('Tu acceso a esta ONG está desactivado. Escríbele a tu ONG.')
    if created:
        # Only a greeting. Joining never sends an event; those go out by hand (manage.py send_event).
        transaction.on_commit(lambda: send_welcome(phone))
    return member, created


def incident_images(ong: Ong) -> QuerySet[SatelliteImage]:
    """Scenes on the ONG's rivers that alerted someone, newest first, as a queryset to page or count.

    Only scenes captured up to the API's clock: with the demo clock, the later ones do not exist yet.
    The pk tiebreak keeps pages stable when two scenes share a capture time.
    """
    alerting = Detection.objects.filter(confidence__gte=settings.ALERT_MIN_CONFIDENCE).order_by('-confidence')
    return (
        clock.visible(SatelliteImage.objects)
        .filter(river__in=ong.rivers.all(), detections__confidence__gte=settings.ALERT_MIN_CONFIDENCE)
        .distinct().select_related('river')
        .prefetch_related(Prefetch('detections', queryset=alerting, to_attr='alerting'))
        .order_by('-captured_at', '-pk')
    )


def with_expedientes(ong: Ong, images) -> list[tuple[SatelliteImage, list[Detection], Expediente | None]]:
    """Each scene with its alerting detections and the ONG's expediente for it, if any."""
    images = list(images)
    expedientes = {
        e.image_id: e for e in Expediente.objects.filter(ong=ong, image__in=images)
        .select_related('updated_by').prefetch_related('authorities', 'filings')
    }
    return [(image, image.alerting, expedientes.get(image.pk)) for image in images]


def incidents(ong: Ong) -> list[tuple[SatelliteImage, list[Detection], Expediente | None]]:
    """The newest INCIDENT_LIMIT incidents (condorin.pe's unpaged panel)."""
    return with_expedientes(ong, incident_images(ong)[:INCIDENT_LIMIT])


def incident_totals(ong: Ong) -> dict:
    """Counts over every incident of the ONG (not just one page), computed in the database."""
    images = incident_images(ong).order_by().prefetch_related(None)
    total = images.count()
    by_status = dict(
        Expediente.objects.filter(ong=ong, image__in=images.values('pk'))
        .order_by().values_list('status').annotate(n=Count('pk'))
    )
    return {
        'incidents': total,
        'without_expediente': total - sum(by_status.values()),
        'draft': by_status.get(Expediente.Status.DRAFT, 0),
        'ready': by_status.get(Expediente.Status.READY, 0),
        'filed': by_status.get(Expediente.Status.FILED, 0),
    }


def open_from_panel(member: Member, image_id: int) -> Alert:
    """The member's personal link to the expediente of one scene, created when they had no alert for it."""
    image = SatelliteImage.objects.filter(pk=image_id, river__ongs=member.ong).first()
    if image is None or not image.alerting_detections().exists():
        raise NotFound('No encontramos esa detección en los ríos de tu ONG.')
    alert, _ = Alert.objects.get_or_create(image=image, member=member, defaults={'status': Alert.Status.PANEL})
    if alert.is_expired:
        # The member is signed in, so an old link of theirs can simply be renewed.
        alert.expires_at = default_expiry()
        alert.save(update_fields=['expires_at', 'updated'])
    return alert


def sign_in_by_link(token: str) -> Member:
    """The member a WhatsApp alert link was sent to, if that link may still sign them in.

    Only links actually delivered by WhatsApp count (whoever holds them holds that phone's chat), and
    only for LINK_SIGN_IN_DAYS. Anything else gets the same 404, so nothing leaks.

    The window is a security window, so it runs on the real clock: from the alert row's real creation
    (`created`, it is sent right after), never from `sent_at`, which follows the demo clock. Moving the demo
    day neither stretches nor cuts it.
    """
    alert = (Alert.objects.select_related('member__ong')
             .filter(token=token, status=Alert.Status.SENT, member__active=True, member__ong__active=True)
             .first())
    window = timedelta(days=settings.LINK_SIGN_IN_DAYS)
    if alert is None or alert.is_expired or not alert.sent_at or timezone.now() > alert.created + window:
        raise NotFound('Este enlace no permite iniciar sesión.')
    if alert.member.ong.internal:
        # An admin's alert signs them in as their own ONG member, never as the hidden internal team.
        return member_for_phone(alert.member.phone)[0]
    return alert.member


def missing_count(expediente: Expediente) -> int:
    return len(missing_fields(expediente))


def crop_url(detection) -> str | None:
    """Signed link to the pinned version of a detection's crop, or None when it cannot be signed."""
    if not detection.crop_uri:
        return None
    try:
        bucket, name, generation = gcs.parse_gs_uri(detection.crop_uri)
    except ValueError:
        return None
    return gcs.signed_url(bucket, name, detection.crop_generation or generation)
