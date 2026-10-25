"""What an ONG has already seen and done at a place, kept in Atomic Memory and shown again when the same place comes back.

Each ONG is one memory subject (`<prefix>:ong:<id>`, no member, phone or name). Memories are written from events
the app already knows (the ONG rejected a detection and why, confirmed one, verified one in the field, filed an
expediente) and read back, by river and distance, beside a new incident of that ONG. They are reference only: they
never change a detection, an alert, a triage, the hechos or the evidence, and the member decides what to do with them.

Same switch and the same guarded client as the field notes (`notas.enabled`, `notas.call`). Writes are best effort
after the commit and never fail the request; a read that cannot be answered says so instead of guessing.
"""
import logging
import math
import threading
from dataclasses import dataclass

from django.conf import settings
from django.db import close_old_connections, transaction

from . import notas

logger = logging.getLogger(__name__)

SOURCE_SITE = 'condorin-antecedentes'
KIND = 'antecedente'
# Only a place this close counts as "the same place"; Atomic Memory ranks, this decides.
RADIUS_KM = 3.0
SEARCH_LIMIT = 25
SHOWN = 5

TRIAGE_EVENT = {
    'confirmed': 'confirmada',
    'false_positive': 'rechazada',
    'verified_field': 'verificada',
}
EVENT_LABEL = {
    'confirmada': 'Marcada como draga',
    'rechazada': 'Marcada como no es una draga',
    'verificada': 'Verificada en campo',
    'presentada': 'Denuncia presentada',
}


@dataclass(frozen=True)
class Antecedente:
    id: str
    event: str
    text: str
    image_id: int
    created_at: str
    distance_km: float

    def as_dict(self) -> dict:
        return {'id': self.id, 'event': self.event, 'event_label': EVENT_LABEL.get(self.event, ''),
                'text': self.text, 'image_id': self.image_id, 'created_at': self.created_at,
                'distance_km': round(self.distance_km, 1)}


def subject(ong) -> str:
    return f'{settings.ATOMIC_MEMORY_SUBJECT_PREFIX}:ong:{ong.pk}'


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def point(image) -> tuple[float, float] | None:
    """Where the scene's strongest detection is."""
    best = image.detections.order_by('-confidence').first()
    return (float(best.lat), float(best.lon)) if best else None


def _query(image) -> str:
    return f'Antecedentes en el río {image.river.name} {image.river.region}'.strip()


def record(ong, image, event: str, text: str) -> None:
    """Stores one antecedente. Raises nothing: a failure is logged and the app goes on."""
    if not notas.enabled():
        return
    where = point(image)
    if where is None:
        return
    try:
        data = notas.call('POST', '/v1/memories/ingest/quick', body={
            'user_id': subject(ong),
            'conversation': f'{_query(image)}: {text}',
            'source_site': SOURCE_SITE,
            'skip_extraction': True,
            'content_class': 'summary',
            'metadata': {
                'condorin_kind': KIND, 'condorin_event': event, 'condorin_text': text,
                'condorin_image': image.pk, 'condorin_river': image.river.slug,
                'condorin_lat': where[0], 'condorin_lon': where[1],
            },
        })
        if not data.get('stored_memory_ids'):
            logger.warning('atomic memory: antecedente %s for image %s was not stored', event, image.pk)
    except notas.MemoryUnavailable:
        logger.warning('atomic memory: antecedente %s for image %s was not saved', event, image.pk)


def triage_text(triage) -> str:
    from detections.text import fecha_larga

    reason = f' ({triage.get_reason_display()})' if triage.reason else ''
    return f'{triage.get_status_display()}{reason}. Escena del {fecha_larga(triage.image.captured_at)}.'


def filing_text(filing) -> str:
    from detections.text import fecha_larga

    return (f'Denuncia presentada ante {filing.authority.name}, registro {filing.receipt_number}. '
            f'Escena del {fecha_larga(filing.expediente.image.captured_at)}.')


def _run(ong_id: int, image_id: int, event: str, text: str, thread: bool = False) -> None:
    from detections.models import SatelliteImage
    from ongs.models import Ong

    try:
        ong = Ong.objects.get(pk=ong_id)
        image = SatelliteImage.objects.select_related('river').get(pk=image_id)
        record(ong, image, event, text)
    except Exception:
        logger.exception('atomic memory: antecedente %s for image %s crashed', event, image_id)
    finally:
        if thread:  # a thread owns its connection; inline work shares the caller's
            close_old_connections()


def record_later(ong, image, event: str, text: str) -> None:
    """After the surrounding transaction commits, on a thread (inline when ALERTS_INLINE, as the other background work)."""
    if not notas.enabled():
        return

    def go():
        if getattr(settings, 'ALERTS_INLINE', False):
            _run(ong.pk, image.pk, event, text)
            return
        try:
            threading.Thread(target=_run, args=(ong.pk, image.pk, event, text, True), daemon=True,
                             name=f'memoria-{image.pk}').start()
        except RuntimeError:
            _run(ong.pk, image.pk, event, text)

    transaction.on_commit(go)


def _current(ong, image_ids: set[int]) -> dict[int, str]:
    """The triage each of these scenes has now, so an undone decision stops being an antecedente."""
    from detections.models import Triage

    return dict(Triage.objects.filter(ong=ong, image_id__in=image_ids).values_list('image_id', 'status'))


def recall(ong, image) -> list[Antecedente]:
    """The ONG's antecedentes within RADIUS_KM of this scene, nearest first. Raises notas.MemoryUnavailable."""
    here = point(image)
    if here is None:
        return []
    data = notas.call('POST', '/v1/memories/search/fast', body={
        'user_id': subject(ong), 'query': _query(image), 'limit': SEARCH_LIMIT, 'source_site': SOURCE_SITE,
    })
    rows = data.get('memories')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise notas.MemoryUnavailable()
    found = []
    for row in rows:
        meta = row.get('metadata')
        if not isinstance(meta, dict) or meta.get('condorin_kind') != KIND:
            continue
        try:
            image_id, lat, lon = int(meta['condorin_image']), float(meta['condorin_lat']), float(meta['condorin_lon'])
        except (KeyError, TypeError, ValueError):
            continue
        text, event, memory_id = meta.get('condorin_text'), meta.get('condorin_event'), notas._uuid(row.get('id'))
        if image_id == image.pk or not isinstance(text, str) or event not in EVENT_LABEL or memory_id is None:
            continue
        distance = km(here[0], here[1], lat, lon)
        if distance <= RADIUS_KM:
            found.append(Antecedente(memory_id, event, text, image_id, str(row.get('created_at') or ''), distance))
    now = _current(ong, {a.image_id for a in found})
    found = [a for a in found
             if a.event in ('presentada',) or a.image_id in now and TRIAGE_EVENT.get(now[a.image_id]) == a.event]
    return sorted(found, key=lambda a: (a.distance_km, a.created_at))[:SHOWN]
