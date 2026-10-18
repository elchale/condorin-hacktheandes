"""The admin live feed: every scene the detector posted and each decision Ojo de Cóndor took about it.

The shape is fixed by condorin/src/lib/admin/activity.ts. Steps are computed here, in order, so the
frontend only shows and animates them.
"""
from django.conf import settings
from django.db.models import Count, Prefetch, Q

from core import clock
from core.geo import coord
from detections.models import Alert, SatelliteImage
from detections.text import fecha_larga
from expedientes.codes import phone_hint
from expedientes.models import Authority, Expediente
from expedientes.services import default_authorities, missing_fields
from ongs.models import Ong

from .services import crop_url, status_label

DEFAULT_LIMIT = 20
MAX_LIMIT = 50

STEPS = {
    'received': 'Imagen recibida',
    'detections': 'Detecciones evaluadas',
    'evidence': 'Evidencia fijada',
    'routing': 'ONG que vigilan el río',
    'alerts': 'Alertas por WhatsApp',
    'opened': 'Expediente abierto',
    'expediente': 'Expediente confirmado',
    'filed': 'Denuncia presentada',
}

# How an authority is named inside a sentence; the full name stays in the lists.
SHORT_AUTHORITY = {
    Authority.Kind.FISCALIA: 'FEMA',
    Authority.Kind.OEFA: 'OEFA',
    Authority.Kind.SERNANP: 'SERNANP',
    Authority.Kind.POLICIA: 'la Policía',
    Authority.Kind.MARINA: 'DICAPI',
}


def parse_limit(value) -> int:
    try:
        return max(1, min(int(value), MAX_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def activity_feed(limit: int = DEFAULT_LIMIT) -> dict:
    threshold = settings.ALERT_MIN_CONFIDENCE
    watching = Ong.objects.filter(active=True, internal=False).annotate(
        active_members=Count('members', filter=Q(members__active=True)),
    ).order_by('pk')
    images = (
        clock.visible(SatelliteImage.objects).select_related('river')
        .prefetch_related(
            'detections',
            Prefetch('river__ongs', queryset=watching, to_attr='watching'),
            Prefetch('alerts', queryset=Alert.objects.select_related('member__ong').order_by('pk')),
            Prefetch('expedientes', queryset=Expediente.objects.select_related('ong', 'created_by').prefetch_related(
                'authorities', 'filings__authority')),
        )
        .order_by('-created', '-pk')[:limit]
    )
    suggested = {}
    events = []
    for image in images:
        if image.river_id not in suggested:
            suggested[image.river_id] = [a.name for a in default_authorities(image.river)]
        events.append(_event(image, threshold, suggested[image.river_id]))
    return {'generated_at': clock.now(), 'clock': clock.payload(), 'threshold': threshold, 'events': events}


def _event(image, threshold: float, authorities: list[str]) -> dict:
    detections = sorted(image.detections.all(), key=lambda d: d.index)
    alerting = [d for d in detections if d.confidence >= threshold]
    ongs = image.river.watching
    routed = [o for o in ongs if o.active_members]
    if not alerting:
        decision = 'below_threshold'
    elif not routed:
        decision = 'no_watchers'
    else:
        decision = 'alerted'

    ong_ids = {o.pk for o in ongs}
    alerts = [a for a in image.alerts.all() if a.member.ong_id in ong_ids]
    expedientes = [e for e in image.expedientes.all() if e.ong_id in ong_ids]
    by_ong = {e.ong_id: e for e in expedientes}

    return {
        'id': image.pk,
        'received_at': image.created,
        'captured_at': image.captured_at,
        'captured_at_label': fecha_larga(image.captured_at),
        'satellite': image.satellite,
        'model': f'{image.model_name} {image.model_version}',
        'river': {'slug': image.river.slug, 'name': image.river.name, 'protected_area': image.river.protected_area},
        'scene': {'uri': image.gs_uri, 'pinned': bool(image.md5_hash)},
        'detections': [{
            'index': d.index,
            'lat': coord(d.lat),
            'lon': coord(d.lon),
            'confidence': round(d.confidence, 3),
            'alerting': d.confidence >= threshold,
            'crop_url': crop_url(d),
            'pinned': bool(d.crop_sha256),
        } for d in detections],
        'decision': decision,
        'ongs': [{
            'id': o.pk,
            'name': o.display_name,
            'members': o.active_members,
            'alerts': [_alert(a) for a in alerts if a.member.ong_id == o.pk],
            'expediente': _expediente(by_ong.get(o.pk)),
        } for o in ongs],
        'authorities_suggested': authorities,
        'steps': _steps(image, threshold, detections, alerting, ongs, routed, decision, alerts, expedientes),
    }


def _alert(alert) -> dict:
    return {
        'member': alert.member.full_name or 'Miembro',
        'phone_hint': phone_hint(alert.member.phone),
        'status': alert.status,
        'sent_at': alert.sent_at,
        'opened_at': alert.opened_at,
    }


def _expediente(expediente) -> dict | None:
    if expediente is None:
        return None
    return {
        'status': expediente.status,
        'status_label': status_label(expediente),
        'folio': expediente.folio,
        'authorities': [a.name for a in expediente.authorities.all()],
        'filings': [{'authority': f.authority.name, 'receipt_number': f.receipt_number, 'filed_at': f.filed_at}
                    for f in expediente.filings.all()],
        'finalized_at': expediente.finalized_at,
    }


def _step(key: str, state: str, detail: str, at=None) -> dict:
    return {'key': key, 'label': STEPS[key], 'detail': detail, 'state': state, 'at': at}


def _steps(image, threshold, detections, alerting, ongs, routed, decision, alerts, expedientes) -> list[dict]:
    river = image.river.name
    skip = decision != 'alerted'
    return [
        _step('received', 'done', (
            f'Imagen {image.satellite} del {fecha_larga(image.captured_at)}, río {river}, '
            f'modelo {image.model_name} {image.model_version}.'
        ), image.created),
        _step('detections', 'done', _detections_detail(threshold, detections, alerting), image.created),
        _evidence(image, alerting),
        _routing(decision, river, ongs, routed, image.created),
        _alerts(skip, alerts),
        _opened(skip, alerts, expedientes),
        _confirmed(skip, expedientes),
        _filed(skip, expedientes),
    ]


def _pct(value: float) -> str:
    return f'{round(value * 100)}%'


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f'{", ".join(names[:-1])} y {names[-1]}'


def _short(authority) -> str:
    return SHORT_AUTHORITY.get(authority.kind, authority.name)


def _detections_detail(threshold, detections, alerting) -> str:
    if not alerting:
        return f'Ninguna detección supera el umbral de {_pct(threshold)}. No se avisa a nadie.'
    best = _pct(max(d.confidence for d in alerting))
    if len(detections) == 1:
        return f'La única detección supera el umbral de {_pct(threshold)} ({best}).'
    verb = 'supera' if len(alerting) == 1 else 'superan'
    return (f'{len(alerting)} de {len(detections)} detecciones {verb} el umbral de {_pct(threshold)} '
            f'(la más alta, {best}).')


def _evidence(image, alerting) -> dict:
    crops = [d for d in alerting if d.crop_uri]
    if not image.md5_hash or any(not d.crop_sha256 for d in crops):
        return _step('evidence', 'pending', 'Esperando acceso al bucket para fijar las huellas.')
    # Nothing else writes these rows, so their last update is when the hashes were stored.
    at = max([image.updated] + [d.updated for d in crops])
    detail = 'Huella MD5 de la escena fijada en el bucket'
    if crops:
        detail += f' y SHA256 de {len(crops)} {"recorte" if len(crops) == 1 else "recortes"}'
    return _step('evidence', 'done', detail + '.', at)


def _routing(decision, river, ongs, routed, at) -> dict:
    if decision == 'below_threshold':
        return _step('routing', 'skipped', 'Sin detecciones sobre el umbral, no hace falta buscar a quién avisar.')
    if decision == 'no_watchers':
        if ongs:
            return _step('routing', 'failed', f'Las ONG que vigilan el río {river} no tienen miembros activos.', at)
        return _step('routing', 'failed', f'Ninguna ONG vigila el río {river}.', at)
    members = sum(o.active_members for o in routed)
    names = _join([o.display_name for o in routed])
    count = 'Lo vigila 1 ONG' if len(routed) == 1 else f'Lo vigilan {len(routed)} ONG'
    people = '1 miembro' if members == 1 else f'{members} miembros'
    return _step('routing', 'done', f'{count}: {names} ({people}).', at)


def _alerts(skip, alerts) -> dict:
    if skip:
        return _step('alerts', 'skipped', 'No hay a quién avisar.')
    whatsapp = [a for a in alerts if a.status != Alert.Status.PANEL]
    sent = [a for a in whatsapp if a.status == Alert.Status.SENT]
    failed = sum(a.status == Alert.Status.FAILED for a in whatsapp)
    queued = sum(a.status == Alert.Status.PENDING for a in whatsapp)
    if sent:
        detail = f'{len(sent)} {"alerta enviada" if len(sent) == 1 else "alertas enviadas"} por WhatsApp'
        if failed:
            detail += f', {failed} {"falló" if failed == 1 else "fallaron"}'
        if queued:
            detail += f', {queued} en cola'
        first = min((a.sent_at for a in sent if a.sent_at), default=None)
        return _step('alerts', 'done', detail + '.', first)
    if queued:
        return _step('alerts', 'pending', f'{queued} {"alerta" if queued == 1 else "alertas"} en cola para WhatsApp.')
    if failed:
        return _step('alerts', 'failed', 'Ninguna alerta llegó: WhatsApp rechazó todos los envíos.')
    return _step('alerts', 'skipped', 'Los miembros se unieron después de esta imagen, no se les envió alerta.')


def _opened(skip, alerts, expedientes) -> dict:
    opened = sorted((a for a in alerts if a.opened_at), key=lambda a: a.opened_at)
    if opened:
        first = opened[0]
        who = first.member.full_name or 'Un miembro'
        return _step('opened', 'done', f'{who} abrió el expediente de {first.member.ong.display_name}.',
                     first.opened_at)
    touched = [e for e in expedientes if not e.auto_created or e.updated_by_id]
    if touched:
        first = min(touched, key=lambda e: e.created)
        who = first.created_by.full_name if first.created_by and first.created_by.full_name else 'Un miembro'
        return _step('opened', 'done', f'{who} abrió el expediente de {first.ong.display_name}.', first.created)
    if expedientes:
        return _step('opened', 'pending', 'El borrador automático está listo, nadie lo abrió todavía.')
    if skip:
        return _step('opened', 'skipped', 'No se envió ninguna alerta que abrir.')
    return _step('opened', 'pending', 'Nadie tocó todavía "Crear expediente".')


def _confirmed(skip, expedientes) -> dict:
    final = sorted((e for e in expedientes if e.finalized_at), key=lambda e: e.finalized_at)
    if final:
        first = final[0]
        to = _join([_short(a) for a in first.authorities.all()])
        return _step('expediente', 'done', f'{first.folio} confirmado con código de WhatsApp, para {to}.',
                     first.finalized_at)
    if expedientes:
        missing = min(len(missing_fields(e)) for e in expedientes)
        if missing:
            detail = f'Borrador en curso, {"falta 1 dato" if missing == 1 else f"faltan {missing} datos"}.'
        else:
            detail = 'Borrador completo, falta confirmarlo con el código de WhatsApp.'
        return _step('expediente', 'pending', detail)
    if skip:
        return _step('expediente', 'skipped', 'No hay expediente porque no se avisó a nadie.')
    return _step('expediente', 'pending', 'Todavía no hay un borrador.')


def _filed(skip, expedientes) -> dict:
    filings = sorted((f for e in expedientes for f in e.filings.all()), key=lambda f: f.filed_at)
    if filings:
        parts = [f'ante {_short(f.authority)} con el número {f.receipt_number}' for f in filings]
        return _step('filed', 'done', f'Presentado {_join(parts)}.', filings[0].filed_at)
    if skip:
        return _step('filed', 'skipped', 'No hay nada que presentar.')
    return _step('filed', 'pending', 'Falta registrar el número de cargo que da la autoridad.')
