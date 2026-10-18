"""River discharge per river from the Open-Meteo Flood API (GloFAS, about 5 km cells, free, no key).

A river point rarely sits on the GloFAS cell of its main channel (the Madre de Dios point reads
0.6 m3/s, the cell next to it 2,400). So every refresh first probes a 5 by 5 grid of cells around each
point (0.05 degree steps, about 11 km each way) for the long term mean, keeps the cell with the
largest mean, and then asks that cell for 7 past days and 7 forecast days. Two requests in total.
"""
from datetime import UTC, datetime, timedelta

from fuentes.http import Meter, get_json
from fuentes.rivers import river_points

ID = 'glofas'
TTL_S = 6 * 3600
ATTRIBUTION = 'Open-Meteo Flood API, GloFAS (Copernicus Emergency Management Service)'
URL = 'https://open-meteo.com/en/docs/flood-api'

FLOOD = 'https://flood-api.open-meteo.com/v1/flood'
MAX_BYTES = 2 * 1024 * 1024
STEP = 0.05
OFFSETS = (-2, -1, 0, 1, 2)
TREND_DAYS = 3
TREND_RATIO = 0.05  # a change under 5 % in TREND_DAYS days is "estable"
LIMA = timedelta(hours=-5)  # Peru has no daylight saving time


def lima_today(now: datetime | None = None) -> str:
    return ((now or datetime.now(UTC)) + LIMA).strftime('%Y-%m-%d')


def _join(values) -> str:
    return ','.join(str(v) for v in values)


def probe_cells(points, meter=None) -> dict[str, tuple[float, float]]:
    """{slug: (lat, lon)} of the cell with the largest mean discharge around each point."""
    grid = [(slug, round(lat + i * STEP, 4), round(lon + j * STEP, 4))
            for slug, lat, lon in points for i in OFFSETS for j in OFFSETS]
    params = {'latitude': _join(g[1] for g in grid), 'longitude': _join(g[2] for g in grid),
              'daily': 'river_discharge_mean', 'forecast_days': 1}
    data = get_json(FLOOD, params, max_bytes=MAX_BYTES, meter=meter)
    best = {}
    for (slug, lat, lon), loc in zip(grid, data if isinstance(data, list) else [data], strict=False):
        values = [v for v in (loc.get('daily') or {}).get('river_discharge_mean', []) if v is not None]
        if values and (slug not in best or values[0] > best[slug][0]):
            best[slug] = (values[0], lat, lon)
    return {slug: (lat, lon) for slug, (_, lat, lon) in best.items()}


def trend(today: float, later: float | None) -> str:
    if later is None or not today:
        return 'estable'
    change = (later - today) / today
    return 'sube' if change > TREND_RATIO else 'baja' if change < -TREND_RATIO else 'estable'


def summarize(location: dict, today: str) -> dict | None:
    """{today_m3s, mean_m3s, trend, series} from one location, or None when the cell has no value today."""
    daily = location.get('daily') or {}
    days, flow, mean = daily.get('time', []), daily.get('river_discharge', []), daily.get('river_discharge_mean', [])
    if today not in days:
        return None
    i = days.index(today)
    if i >= len(flow) or flow[i] is None:
        return None
    ahead = [v for v in flow[i + 1:i + 1 + TREND_DAYS] if v is not None]
    return {'today_m3s': round(flow[i], 1),
            'mean_m3s': round(mean[i], 1) if i < len(mean) and mean[i] is not None else None,
            'trend': trend(flow[i], ahead[-1] if len(ahead) == TREND_DAYS else None),
            'series': [{'date': d, 'm3s': round(v, 1) if v is not None else None}
                       for d, v in zip(days, flow, strict=False)],
            'cell': [location.get('latitude'), location.get('longitude')]}


def fetch(meter: Meter | None = None) -> dict:
    points = river_points()
    if not points:
        return {'rivers': {}}
    cells = probe_cells(points, meter)
    slugs = [slug for slug, _, _ in points]
    coords = [cells.get(slug) or (lat, lon) for slug, lat, lon in points]
    params = {'latitude': _join(c[0] for c in coords), 'longitude': _join(c[1] for c in coords),
              'daily': 'river_discharge,river_discharge_mean', 'past_days': 7, 'forecast_days': 7}
    data = get_json(FLOOD, params, max_bytes=MAX_BYTES, meter=meter)
    today = lima_today()
    rivers = {slug: {'discharge': summarize(loc, today)}
              for slug, loc in zip(slugs, data if isinstance(data, list) else [data], strict=False)}
    missing = [slug for slug, r in rivers.items() if r['discharge'] is None]
    return {'rivers': rivers, 'warnings': [f'sin caudal GloFAS: {", ".join(missing)}'] if missing else []}
