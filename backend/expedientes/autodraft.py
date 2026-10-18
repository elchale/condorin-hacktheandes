"""Draft expedientes created on their own, one per scene and watching ONG, so no incident starts empty.

Every scene with alerting detections gets a prefilled draft for each active, non internal ONG that
watches its river, recent or old, as soon as it is stored. Nothing is sent: no WhatsApp, no email.
`auto_created` marks them and `updated_by` stays empty until a member edits, which is how the panel
tells "Borrador listo para revisar" apart from a draft someone is working on.
"""
import logging

from django.conf import settings
from django.db import transaction

from detections.models import SatelliteImage
from ongs.models import Ong

from . import redaccion
from .drafting import FIELD_OBSERVATIONS, draft_evidence_links, draft_facts, draft_place_reference, draft_risks
from .models import Expediente
from .services import default_authorities, signer

logger = logging.getLogger(__name__)

# Denunciante fields filled from whoever signs when a member first opens an automatic draft.
SIGNER_FIELDS = {'rep_name': 'full_name', 'rep_dni': 'dni', 'rep_position': 'position', 'rep_phone': 'phone'}


def status_label(expediente) -> str:
    """An automatic draft no member has edited yet reads as ready to review, not as work in progress."""
    if expediente.status == expediente.Status.DRAFT and expediente.updated_by_id is None:
        return 'Borrador listo para revisar'
    return expediente.get_status_display()


def watching_ongs(river):
    return Ong.objects.filter(active=True, internal=False, rivers=river).order_by('pk')


def legal_representative(ong: Ong):
    return ong.members.filter(active=True, is_legal_representative=True).exclude(dni='').order_by('pk').first()


def prefill(image: SatelliteImage, ong: Ong) -> dict:
    """The same prefill the link opening writes, with the ONG's legal representative as signer when known."""
    rep = legal_representative(ong)
    place = draft_place_reference(image)
    return {
        'ong_name': ong.name,
        'ong_ruc': ong.ruc,
        'ong_address': ong.address,
        'notify_email': ong.email or (rep.email if rep else ''),
        'rep_name': rep.full_name if rep else '',
        'rep_dni': rep.dni if rep else '',
        'rep_position': rep.position if rep else '',
        'rep_phone': rep.phone if rep else '',
        # Claude polishes the hechos only behind EXPEDIENTE_IA_ENABLED (off by default), as on the link.
        'facts': redaccion.improve_facts(draft_facts(image), place),
        'place_reference': place,
        'field_observations': FIELD_OBSERVATIONS,
        'field_evidence_links': draft_evidence_links(image),
        'suspects': 'Por identificar.',
        'risk_notes': draft_risks(image),
        'auto_created': True,
    }


@transaction.atomic
def create_drafts(image: SatelliteImage) -> list[Expediente]:
    """Creates the missing drafts of one scene. Idempotent on the (image, ong) constraint."""
    if not image.alerting_detections().exists():
        return []
    have = set(Expediente.objects.filter(image=image).values_list('ong_id', flat=True))
    created = []
    for ong in watching_ongs(image.river).exclude(pk__in=have):
        expediente, new = Expediente.objects.get_or_create(image=image, ong=ong, defaults=prefill(image, ong))
        if new:
            expediente.authorities.set(default_authorities(image.river))
            created.append(expediente)
    if created:
        logger.info('expedientes: %s automatic drafts for image %s', len(created), image.pk)
    return created


def missing_pairs() -> list[tuple[SatelliteImage, Ong]]:
    """Every (scene, watching ONG) pair with alerting detections and no expediente yet."""
    images = (SatelliteImage.objects.filter(detections__confidence__gte=settings.ALERT_MIN_CONFIDENCE)
              .distinct().select_related('river').order_by('pk'))
    have = set(Expediente.objects.values_list('image_id', 'ong_id'))
    ongs_by_river = {}
    pairs = []
    for image in images:
        if image.river_id not in ongs_by_river:
            ongs_by_river[image.river_id] = list(watching_ongs(image.river))
        pairs += [(image, ong) for ong in ongs_by_river[image.river_id] if (image.pk, ong.pk) not in have]
    return pairs


def adopt(expediente: Expediente, member) -> Expediente:
    """When a member opens an automatic draft nobody touched, fill the blank signer fields as the link would.

    `updated_by` stays empty: opening is not editing.
    """
    if not expediente.auto_created or expediente.updated_by_id or expediente.status != Expediente.Status.DRAFT:
        return expediente
    rep = signer(member)
    changed = []
    if not expediente.rep_name and not expediente.rep_dni:
        # A whole signer, never a mix of two people.
        changed = [field for field, attr in SIGNER_FIELDS.items() if getattr(rep, attr, '')]
        for field in changed:
            setattr(expediente, field, getattr(rep, SIGNER_FIELDS[field]))
    if not expediente.notify_email and (member.email or rep.email):
        expediente.notify_email = member.email or rep.email
        changed.append('notify_email')
    if changed:
        expediente.save(update_fields=changed + ['updated'])
    return expediente
