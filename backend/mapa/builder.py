"""The public map payload (GET /api/v1/mapa and `manage.py export_mapa`).

Contract A in hacktheandes/mapa-data/CONTRACT.md. Everything here is public: counts, river
metadata and detection points. Never names, phones, tokens or signed URLs.

About eight queries whatever the size of the data: rivers, images, detections, alerts and
expedientes are each read once as plain values and joined in Python.
"""
from collections import Counter, defaultdict
from datetime import UTC, datetime

from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from accounts.models import Member as SiteUser
from core import clock
from detections.models import Alert, Detection, SatelliteImage
from expedientes.models import Expediente
from ongs.models import Member, Ong, River

BRAND_NAME = 'Ojo de Cóndor'

# Caps keep the payload small on a slow phone even if the detector gets busy.
MAX_IMAGES = 500
MAX_DETECTIONS = 3000
MAX_ACTIVITY = 40

# Where a river goes on the map before it has any detection (lat, lon).
RIVER_FALLBACK = {
    'yaguas': (-2.65, -71.35),
    'malinowski': (-12.95, -69.95),
    'nanay': (-3.75, -73.45),
    'madre-de-dios': (-12.60, -69.20),
    'tambopata': (-12.85, -69.35),
    'inambari': (-13.05, -70.10),
    'napo': (-3.30, -72.80),
    'putumayo': (-2.40, -72.80),
    'maranon': (-4.50, -77.50),
    'marañon': (-4.50, -77.50),
}

# Peruvian Amazon, used when there is nothing to frame yet: [minLon, minLat, maxLon, maxLat].
DEFAULT_BBOX = [-78.5, -14.5, -68.5, -0.5]


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def plural(n: int, one: str, many: str) -> str:
    return f'{n} {one if n == 1 else many}'


def _round(value: float, places: int = 5) -> float:
    return round(float(value), places)


def build_mapa(member: Member | None = None, phone: str | None = None) -> dict:
    """The whole public map. With `phone` (a signed in session) `mine` describes that member."""
    threshold = settings.ALERT_MIN_CONFIDENCE

    rivers = list(
        River.objects.annotate(ong_count=Count('ongs', filter=Q(ongs__active=True, ongs__internal=False), distinct=True))
        .values('id', 'slug', 'name', 'basin', 'region', 'province', 'district', 'protected_area', 'ong_count')
        .order_by('name')
    )
    river_slug = {r['id']: r['slug'] for r in rivers}

    now = clock.now()
    images = list(
        # Only what has happened by the API's clock: the demo clock hides the scenes captured after it.
        SatelliteImage.objects.filter(captured_at__lte=now).order_by('-captured_at')
        .values('id', 'river_id', 'satellite', 'captured_at', 'model_name', 'model_version')[:MAX_IMAGES]
    )
    image_by_id = {i['id']: i for i in images}

    detections = list(
        Detection.objects.filter(image_id__in=image_by_id)
        .order_by('-image__captured_at', '-confidence')
        .values('id', 'image_id', 'lat', 'lon', 'confidence')[:MAX_DETECTIONS]
    )

    alerts = {
        row['image_id']: row for row in
        # The admins' alerts (hidden internal ONG) are not public numbers.
        Alert.objects.filter(image_id__in=image_by_id, member__ong__internal=False).values('image_id').annotate(
            sent=Count('id', filter=Q(status=Alert.Status.SENT)),
            opened=Count('id', filter=Q(opened_at__isnull=False)),
            ongs=Count('member__ong', filter=Q(status=Alert.Status.SENT), distinct=True),
            last_sent=Max('sent_at'),
        )
    }

    expedientes = list(
        Expediente.objects.filter(image_id__in=image_by_id)
        .annotate(filed_at=Min('filings__created'))
        .values('id', 'image_id', 'status', 'created', 'updated', 'filed_at', 'auto_created', 'updated_by_id')
    )

    totals_counts = {
        'ongs': Ong.objects.filter(active=True, internal=False).count(),
        'members': Member.objects.filter(active=True, ong__active=True, ong__internal=False).count(),
        'users': SiteUser.objects.count(),
    }

    # Per image: detections, alerting, best detection; per river: centroid of its detections.
    per_image = defaultdict(list)
    for d in detections:
        per_image[d['image_id']].append(d)
    river_points = defaultdict(list)
    features = []
    for d in detections:
        image = image_by_id[d['image_id']]
        lat, lon = _round(d['lat']), _round(d['lon'])
        slug = river_slug.get(image['river_id'])
        river_points[image['river_id']].append((lat, lon))
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {
                'id': d['id'], 'image': image['id'], 'river': slug,
                'confidence': round(d['confidence'], 3), 'captured_at': iso(image['captured_at']),
                'alerting': d['confidence'] >= threshold, 'satellite': image['satellite'], 'kind': 'draga',
            },
        })

    exp_by_image = defaultdict(Counter)
    for e in expedientes:
        exp_by_image[e['image_id']][e['status']] += 1

    image_rows = []
    for image in images:
        dets = per_image.get(image['id'], [])
        best = max(dets, key=lambda d: d['confidence'], default=None)
        counts = exp_by_image.get(image['id'], Counter())
        image_rows.append({
            'id': image['id'],
            'river': river_slug.get(image['river_id']),
            'satellite': image['satellite'],
            'captured_at': iso(image['captured_at']),
            'model': f"{image['model_name']} {image['model_version']}".strip(),
            'detections': len(dets),
            'alerting': sum(1 for d in dets if d['confidence'] >= threshold),
            'top_confidence': round(best['confidence'], 3) if best else None,
            'lat': _round(best['lat']) if best else None,
            'lon': _round(best['lon']) if best else None,
            'alerts_sent': alerts.get(image['id'], {}).get('sent', 0),
            'expedientes': {s: counts.get(s, 0) for s in ('draft', 'ready', 'filed')},
        })

    river_images = Counter(i['river_id'] for i in images)
    river_detections = Counter(image_by_id[d['image_id']]['river_id'] for d in detections)
    river_last = {}
    for image in images:  # newest first, so the first one seen is the latest
        river_last.setdefault(image['river_id'], image['captured_at'])

    river_rows = []
    for r in rivers:
        points = river_points.get(r['id'])
        if points:
            lat = _round(sum(p[0] for p in points) / len(points))
            lon = _round(sum(p[1] for p in points) / len(points))
        else:
            lat, lon = RIVER_FALLBACK.get(r['slug'], (None, None))
        river_rows.append({
            'slug': r['slug'], 'name': r['name'], 'basin': r['basin'], 'region': r['region'],
            'province': r['province'], 'district': r['district'], 'protected_area': r['protected_area'],
            'lat': lat, 'lon': lon, 'ongs': r['ong_count'],
            'images': river_images.get(r['id'], 0), 'detections': river_detections.get(r['id'], 0),
            'last_captured_at': iso(river_last.get(r['id'])),
        })

    alert_rows = alerts.values()
    totals = {
        'images': len(images),
        'detections': len(detections),
        'alerting_detections': sum(1 for d in detections if d['confidence'] >= threshold),
        'alerts_sent': sum(a['sent'] for a in alert_rows),
        'alerts_opened': sum(a['opened'] for a in alert_rows),
        'expedientes': len(expedientes),
        'expedientes_filed': sum(1 for e in expedientes if e['status'] == Expediente.Status.FILED),
        **totals_counts,
        'rivers': len(rivers),
    }

    return {
        'generated_at': iso(now),
        'clock': clock.payload(),
        'brand': BRAND_NAME,
        'bbox': _bbox(features, river_rows),
        'totals': totals,
        'rivers': river_rows,
        'images': image_rows,
        'detections': {'type': 'FeatureCollection', 'features': features},
        'timeline': _timeline(images, detections, image_by_id),
        'activity': _activity(images, per_image, alerts, expedientes, image_by_id,
                              {r['id']: r['name'] for r in rivers}, river_slug, now),
        'mine': mine(member, phone) if (member or phone) else None,
    }


def mine(member: Member | None, phone: str | None) -> dict:
    """What a signed in member sees highlighted: their name and their ONG's rivers."""
    if member is None:
        return {'member': {'name': '', 'phone': phone}, 'ong': None}
    return {
        'member': {'name': member.full_name, 'phone': member.phone},
        'ong': {'name': member.ong.display_name,
                'rivers': list(member.ong.rivers.order_by('slug').values_list('slug', flat=True))},
    }


def _bbox(features: list[dict], rivers: list[dict]) -> list[float]:
    points = [f['geometry']['coordinates'] for f in features]
    points += [[r['lon'], r['lat']] for r in rivers if r['lat'] is not None]
    if not points:
        return DEFAULT_BBOX
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    pad = 0.25  # degrees, so a single point still shows its surroundings
    return [round(min(lons) - pad, 4), round(min(lats) - pad, 4), round(max(lons) + pad, 4), round(max(lats) + pad, 4)]


def _month(value: datetime) -> str:
    return timezone.localtime(value).strftime('%Y-%m')


def _timeline(images, detections, image_by_id) -> list[dict]:
    months = defaultdict(lambda: {'images': 0, 'detections': 0})
    for image in images:
        months[_month(image['captured_at'])]['images'] += 1
    for d in detections:
        months[_month(image_by_id[d['image_id']]['captured_at'])]['detections'] += 1
    return [{'month': m, **months[m]} for m in sorted(months)]


def _activity(images, per_image, alerts, expedientes, image_by_id, river_name, river_slug, now) -> list[dict]:
    """Anonymized timeline: what happened, on which river, never who. Nothing dated after the clock."""
    events = []
    for image in images:
        name = river_name.get(image['river_id'], '')
        slug = river_slug.get(image['river_id'])
        n = len(per_image.get(image['id'], []))
        events.append({'at': image['captured_at'], 'kind': 'image', 'river': slug,
                       'label': f'Nueva escena en el río {name} con {plural(n, "detección", "detecciones")}'})
        alert = alerts.get(image['id'])
        if alert and alert['sent'] and alert['last_sent']:
            events.append({'at': alert['last_sent'], 'kind': 'alert', 'river': slug,
                           'label': f'Alerta enviada a {plural(alert["ongs"], "ONG", "ONGs")} del río {name}'})
    for e in expedientes:
        image = image_by_id[e['image_id']]
        name = river_name.get(image['river_id'], '')
        slug = river_slug.get(image['river_id'])
        # Automatic drafts are silent: they count as opened only once a member edits them.
        if not e['auto_created'] or e['updated_by_id']:
            events.append({'at': e['updated'] if e['auto_created'] else e['created'], 'kind': 'expediente_opened',
                           'river': slug, 'label': f'Una ONG abrió un expediente por el río {name}'})
        if e['status'] == Expediente.Status.FILED:
            events.append({'at': e['filed_at'] or e['created'], 'kind': 'expediente_filed', 'river': slug,
                           'label': f'Una ONG presentó la denuncia por el río {name}'})
    events = [ev for ev in events if ev['at'] <= now]
    events.sort(key=lambda ev: ev['at'], reverse=True)
    return [{**ev, 'at': iso(ev['at'])} for ev in events[:MAX_ACTIVITY]]
