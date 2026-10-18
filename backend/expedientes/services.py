"""Open, fill in and finalize an expediente from a personal WhatsApp link."""
import hashlib
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction
from rest_framework.exceptions import NotFound, ValidationError

from core import clock, gcs
from core.exceptions import BaseError
from detections.models import Alert

from . import mailer, redaccion
from .drafting import FIELD_OBSERVATIONS, draft_evidence_links, draft_facts, draft_place_reference, draft_risks
from .models import Authority, Expediente, Filing

logger = logging.getLogger(__name__)


class LinkExpired(BaseError):
    status_code = 410
    default_detail = 'Este enlace venció. Pide a tu ONG que te reenvíe la alerta.'


class ExpedienteLocked(BaseError):
    status_code = 409
    default_detail = 'El expediente ya fue presentado y no se puede modificar.'


# What has to be filled in before the expediente can be finalized, with the message the frontend shows.
REQUIRED = {
    'ong_name': 'Escribe la razón social de la ONG.',
    'ong_address': 'Escribe el domicilio de la ONG.',
    'notify_email': 'Escribe un correo para recibir las notificaciones.',
    'rep_name': 'Escribe el nombre de quien firma la denuncia.',
    'rep_dni': 'Escribe el DNI de quien firma la denuncia.',
    'facts': 'Describe los hechos.',
}

# Denunciante fields that are remembered on the member and the ONG for the next expediente.
MEMBER_FIELDS = {'rep_dni': 'dni', 'rep_position': 'position'}
ONG_FIELDS = {'ong_ruc': 'ruc', 'ong_address': 'address', 'notify_email': 'email'}


def alert_for_token(token: str) -> Alert:
    alert = (Alert.objects.select_related('member__ong', 'image__river')
             .filter(token=token, member__active=True, member__ong__active=True).first())
    if alert is None:
        raise NotFound('No encontramos este expediente. Revisa que el enlace esté completo.')
    if alert.is_expired:
        raise LinkExpired()
    return alert


def default_authorities(river):
    linked = river.authorities.filter(active=True)
    chosen = linked.filter(is_primary=True)
    if river.protected_area:
        chosen = chosen | linked.filter(kind=Authority.Kind.SERNANP)
    if not chosen.exists():
        chosen = Authority.objects.filter(active=True, is_primary=True)
    return chosen.distinct()


def signer(member):
    """Who signs by default: the member if their name and DNI are known, else the ONG's legal representative.

    Everything is prefilled so the member only reviews; they can still change the signer in the form.
    """
    if member.full_name and member.dni:
        return member
    rep = member.ong.members.filter(active=True, is_legal_representative=True).exclude(dni='').first()
    return rep or member


def notify_opened(alert_id: int) -> None:
    """Emails the admins after the first tap, on a thread, or inline when ALERTS_INLINE."""
    def run():
        mailer.notify_admins_opened(Alert.objects.select_related('member__ong', 'image__river').get(pk=alert_id))

    def run_in_thread():
        try:
            run()
        except Exception:
            logger.exception('alert %s: admin notification crashed', alert_id)
        finally:
            close_old_connections()

    if getattr(settings, 'ALERTS_INLINE', False):
        run()
        return
    threading.Thread(target=run_in_thread, daemon=True, name=f'opened-{alert_id}').start()


@transaction.atomic
def open_expediente(alert: Alert) -> Expediente:
    """The ONG's expediente for this image; created and prefilled on the first tap."""
    if alert.opened_at is None:
        alert.opened_at = clock.now()
        alert.save(update_fields=['opened_at', 'updated'])
        transaction.on_commit(lambda: notify_opened(alert.pk))

    member, ong, image = alert.member, alert.member.ong, alert.image
    # Drafting (and the Claude call behind it) only runs when the expediente does not exist yet.
    expediente = Expediente.objects.select_for_update().filter(image=image, ong=ong).first()
    if expediente is not None:
        return expediente
    rep = signer(member)
    place = draft_place_reference(image)
    expediente, created = Expediente.objects.select_for_update().get_or_create(
        image=image, ong=ong,
        defaults={
            'ong_name': ong.name,
            'ong_ruc': ong.ruc,
            'ong_address': ong.address,
            'notify_email': ong.email or member.email or rep.email,
            'rep_name': rep.full_name,
            'rep_dni': rep.dni,
            'rep_position': rep.position,
            'rep_phone': rep.phone,
            'facts': redaccion.improve_facts(draft_facts(image), place),
            'place_reference': place,
            'field_observations': FIELD_OBSERVATIONS,
            'field_evidence_links': draft_evidence_links(image),
            'suspects': 'Por identificar.',
            'risk_notes': draft_risks(image),
            'created_by': member,
            'updated_by': member,
        },
    )
    if created:
        expediente.authorities.set(default_authorities(image.river))
        logger.info('expediente %s opened by member %s', expediente.pk, member.pk)
    return expediente


def missing_fields(expediente: Expediente) -> dict:
    missing = {f: msg for f, msg in REQUIRED.items() if not str(getattr(expediente, f) or '').strip()}
    if not expediente.truth_declared:
        missing['truth_declared'] = 'Confirma que los hechos son verdaderos.'
    if not expediente.authorities.exists():
        missing['authorities'] = 'Elige al menos una autoridad.'
    return missing


@transaction.atomic
def update_expediente(expediente: Expediente, member, data: dict) -> Expediente:
    filings = data.pop('filings', None)
    authorities = data.pop('authorities', None)
    reopen = data.pop('reopen', False)

    if reopen:
        if expediente.status == Expediente.Status.FILED:
            raise ExpedienteLocked()
        expediente.status = Expediente.Status.DRAFT

    if data or authorities is not None:
        if expediente.status != Expediente.Status.DRAFT:
            raise ExpedienteLocked(
                'El expediente ya está listo. Para corregirlo, ábrelo de nuevo y vuelve a confirmarlo.'
                if expediente.status == Expediente.Status.READY else None
            )
        for field, value in data.items():
            setattr(expediente, field, value)
        if authorities is not None:
            expediente.authorities.set(authorities)
        _remember(expediente, member, data)

    if filings:
        if expediente.status == Expediente.Status.DRAFT:
            raise ValidationError({'filings': ['Primero confirma el expediente para obtener el PDF final.']})
        for item in filings:
            Filing.objects.update_or_create(
                expediente=expediente, authority=item['authority'],
                defaults={'receipt_number': item['receipt_number'], 'filed_at': item['filed_at'], 'filed_by': member},
            )
        expediente.status = Expediente.Status.FILED

    expediente.updated_by = member
    expediente.save()
    return expediente


def _remember(expediente: Expediente, member, data: dict) -> None:
    """Copy what the person typed back to their profile and the ONG, so next time it is prefilled."""
    if expediente.rep_phone == member.phone:
        _copy(member, MEMBER_FIELDS, data, only_empty=False)
        # People who joined from condorin.pe have no name yet; the first one they sign with becomes it.
        _copy(member, {'rep_name': 'full_name'}, data, only_empty=True)
    _copy(member.ong, ONG_FIELDS, data, only_empty=True)


def _copy(target, mapping: dict, data: dict, only_empty: bool) -> None:
    changed = [attr for field, attr in mapping.items()
               if data.get(field) and not (only_empty and getattr(target, attr))]
    for field, attr in mapping.items():
        if attr in changed:
            setattr(target, attr, data[field])
    if changed:
        target.save(update_fields=changed + ['updated'])


def archive_pdf(expediente: Expediente) -> str:
    """Stores the final PDF in the expedientes bucket. Every confirmation gets its own object, named by
    folio and hash, so a reopened and reconfirmed expediente never overwrites the earlier version."""
    bucket = settings.GCS_EXPEDIENTES_BUCKET
    if not bucket:
        return ''
    name = f'expedientes/{expediente.finalized_at:%Y}/{expediente.folio}-{expediente.pdf_sha256[:16]}.pdf'
    try:
        generation = gcs.upload(bucket, name, bytes(expediente.pdf), 'application/pdf')
    except gcs.StorageUnavailable as exc:
        logger.warning('expediente %s: could not archive the PDF in GCS: %s', expediente.pk, exc)
        return ''
    return f'gs://{bucket}/{name}#{generation}'


@transaction.atomic
def finalize(expediente: Expediente, member) -> Expediente:
    from .pdf import build_pdf

    expediente.status = Expediente.Status.READY
    expediente.finalized_by = member
    expediente.finalized_at = clock.now()
    if not expediente.folio:
        expediente.folio = f'CND-{expediente.finalized_at:%Y}-{expediente.pk:05d}'
    expediente.pdf = build_pdf(expediente, final=True)
    expediente.pdf_sha256 = hashlib.sha256(expediente.pdf).hexdigest()
    expediente.pdf_gcs_uri = archive_pdf(expediente)
    expediente.updated_by = member
    expediente.save()
    return expediente
