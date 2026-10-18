"""Open-Meteo weather per river (no key): rain in the last 24 hours and 7 days, current temperature,
and the daily forecast for the next 7 days (rain, rain probability, maximum temperature).

All rivers go in one request (Open-Meteo takes comma separated coordinates). Times come back in
America/Lima; `utc_offset_seconds` turns the hourly ones back into UTC.
"""
from datetime import UTC, datetime, timedelta

from fuentes.http import Meter, get_json
from fuentes.rivers import river_points

ID = 'open-meteo'
TTL_S = 3 * 3600
ATTRIBUTION = 'Open-Meteo.com (CC BY 4.0)'
URL = 'https://open-meteo.com/'

FORECAST = 'https://api.open-meteo.com/v1/forecast'
MAX_BYTES = 2 * 1024 * 1024
FORECAST_DAYS = 7
DAILY = 'precipitation_sum,precipitation_probability_max,temperature_2m_max'


def _utc(text: str, offset_s: int = 0) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC) - timedelta(seconds=offset_s)


def forecast(location: dict, today: str) -> list[dict]:
    """The daily rows from `today` (a local YYYY-MM-DD) on, at most FORECAST_DAYS."""
    daily = location.get('daily') or {}
    rows = zip(daily.get('time', []), daily.get('precipitation_sum', []),
               daily.get('precipitation_probability_max', []), daily.get('temperature_2m_max', []), strict=False)
    return [{'date': day, 'rain_mm': rain, 'rain_prob': prob, 'tmax_c': tmax}
            for day, rain, prob, tmax in rows if day >= today][:FORECAST_DAYS]


def summarize(location: dict) -> dict:
    offset = location.get('utc_offset_seconds') or 0
    current = location.get('current') or {}
    now = _utc(current['time'], offset) if current.get('time') else datetime.now(UTC)
    hourly = location.get('hourly') or {}
    rain = [(_utc(t, offset), v or 0.0) for t, v in zip(hourly.get('time', []), hourly.get('precipitation', []))]
    rain = [(t, v) for t, v in rain if t <= now]
    days = forecast(location, (now + timedelta(seconds=offset)).strftime('%Y-%m-%d'))
    return {'rain_mm_7d': round(sum(v for t, v in rain if t > now - timedelta(days=7)), 1),
            'rain_mm_24h': round(sum(v for t, v in rain if t > now - timedelta(hours=24)), 1),
            'temp_c': current.get('temperature_2m'),
            'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'forecast': days,
            'rain_mm_next_3d': round(sum(d['rain_mm'] or 0.0 for d in days[:3]), 1) if days else None}


def fetch(meter: Meter | None = None) -> dict:
    points = river_points()
    if not points:
        return {'rivers': {}}
    params = {'latitude': ','.join(str(p[1]) for p in points), 'longitude': ','.join(str(p[2]) for p in points),
              'current': 'temperature_2m,precipitation', 'hourly': 'precipitation', 'daily': DAILY,
              'past_days': 7, 'forecast_days': FORECAST_DAYS, 'timezone': 'America/Lima'}
    data = get_json(FORECAST, params, max_bytes=MAX_BYTES, meter=meter)
    locations = data if isinstance(data, list) else [data]
    return {'rivers': {slug: summarize(loc) for (slug, _, _), loc in zip(points, locations, strict=False)}}
