"""NASA FIRMS active fires (VIIRS 375 m), the public 7 day CSV exports for South America. No key.

Each file is about 5 MB; it is streamed and only rows inside the Amazon lowland box are parsed fully.
The box drops the Andes and the coast (farm and grass burns there are not mining). Besides the points
(the 2,000 hottest), `near_rivers` counts every deduplicated fire within 25 km of each river point.
"""
import csv
import logging
import math
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from fuentes.http import Meter, stream_lines
from fuentes.rivers import river_points

logger = logging.getLogger(__name__)

ID = 'firms'
TTL_S = 3600
ATTRIBUTION = 'NASA FIRMS (VIIRS 375 m, S-NPP, NOAA-20, NOAA-21)'
URL = 'https://firms.modaps.eosdis.nasa.gov/active_fire/'

BASE = 'https://firms.modaps.eosdis.nasa.gov/data/active_fire'
FILES = {
    'S-NPP': f'{BASE}/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_America_7d.csv',
    'NOAA-20': f'{BASE}/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_America_7d.csv',
    'NOAA-21': f'{BASE}/noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_America_7d.csv',
}
MAX_BYTES = 20 * 1024 * 1024
MAX_FIRES = 2000
# Amazon lowland side of Peru (and a margin over the borders): lon -78.5 to -68, lat -13.5 to 0.5.
BBOX = (-78.5, -13.5, -68.0, 0.5)
NEAR_KM = 25.0
CONFIDENCE = {'nominal': 'n', 'low': 'l', 'high': 'h', 'n': 'n', 'l': 'l', 'h': 'h'}


def parse_rows(lines, since: datetime, bbox=BBOX) -> list[dict]:
    """Fires inside bbox and after `since` from FIRMS CSV lines (header first)."""
    lines = iter(lines)
    header = next(lines, '')
    cols = {name: i for i, name in enumerate(header.strip().split(','))}
    i_lat, i_lon = cols.get('latitude', 0), cols.get('longitude', 1)
    min_lon, min_lat, max_lon, max_lat = bbox
    fires = []
    for line in lines:
        parts = line.split(',')
        if len(parts) < len(cols):
            continue
        try:
            lat, lon = float(parts[i_lat]), float(parts[i_lon])
        except ValueError:
            continue
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        row = next(csv.reader([line]))
        try:
            hhmm = row[cols['acq_time']].zfill(4)
            at = datetime.strptime(f"{row[cols['acq_date']]} {hhmm}", '%Y-%m-%d %H%M').replace(tzinfo=UTC)
            frp = float(row[cols['frp']] or 0)
        except (KeyError, ValueError):
            continue
        if at < since:
            continue
        fires.append({'lat': round(lat, 4), 'lon': round(lon, 4), 'at': at, 'frp': round(frp, 1),
                      'confidence': CONFIDENCE.get(row[cols['confidence']].strip().lower(), 'n')
                      if 'confidence' in cols else 'n',
                      'daynight': row[cols['daynight']].strip() if 'daynight' in cols else ''})
    return fires


def dedupe(fires: list[dict]) -> list[dict]:
    """One fire per spot (about 100 m) and day, the hottest: three satellites see the same fire."""
    best = {}
    for f in fires:
        key = (round(f['lat'], 3), round(f['lon'], 3), f['at'].date())
        if key not in best or f['frp'] > best[key]['frp']:
            best[key] = f
    return list(best.values())


def select(fires: list[dict], limit: int = MAX_FIRES) -> list[dict]:
    """Dedupe and keep the `limit` hottest, newest first."""
    top = sorted(dedupe(fires), key=lambda f: f['frp'], reverse=True)[:limit]
    return sorted(top, key=lambda f: f['at'], reverse=True)


def km_between(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def near_rivers(fires: list[dict], points, radius_km: float = NEAR_KM) -> dict:
    """{slug: {count_7d, max_frp, last_at, radius_km}} over deduplicated fires within radius_km."""
    fires = dedupe(fires)
    out = {}
    for slug, lat, lon in points:
        close = [f for f in fires if abs(f['lat'] - lat) < 0.5 and abs(f['lon'] - lon) < 0.5
                 and km_between(lat, lon, f['lat'], f['lon']) <= radius_km]
        out[slug] = {'count_7d': len(close),
                     'max_frp': max((f['frp'] for f in close), default=None),
                     'last_at': max(f['at'] for f in close).strftime('%Y-%m-%dT%H:%M:%SZ') if close else None,
                     'radius_km': radius_km}
    return out


def to_feature(f: dict) -> dict:
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [f['lon'], f['lat']]},
            'properties': {'at': f['at'].strftime('%Y-%m-%dT%H:%M:%SZ'), 'frp': f['frp'],
                           'confidence': f['confidence'], 'sensor': 'VIIRS', 'daynight': f['daynight']}}


def fetch(meter: Meter | None = None) -> dict:
    since = timezone.now() - timedelta(days=7)
    fires, errors = [], []
    for name, url in FILES.items():
        try:
            fires += parse_rows(stream_lines(url, max_bytes=MAX_BYTES, meter=meter), since)
        except Exception as exc:  # one satellite down must not lose the others
            logger.warning('fuentes: FIRMS %s failed: %s', name, exc)
            errors.append(f'{name}: {exc.__class__.__name__}')
    if len(errors) == len(FILES):
        raise RuntimeError('; '.join(errors))
    selected = select(fires)
    return {'fires': {'type': 'FeatureCollection', 'features': [to_feature(f) for f in selected]},
            'in_bbox': len(fires), 'near_rivers': near_rivers(fires, river_points()), 'warnings': errors}
