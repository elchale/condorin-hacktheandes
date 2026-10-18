"""One plain Spanish sentence per river for the map, built from the served feeds (no dashes)."""
from datetime import datetime, timedelta

LIMA = timedelta(hours=-5)  # Peru has no daylight saving time
DAYS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
NAMES = {'madre-de-dios': 'Madre de Dios', 'maranon': 'Marañón', 'inambari': 'Inambari'}
FLOW = {'sube': 'caudal en subida', 'baja': 'caudal en bajada', 'estable': 'caudal estable'}


def river_name(slug: str, names: dict) -> str:
    return names.get(slug) or NAMES.get(slug) or slug.replace('-', ' ').title()


def _mm(value) -> str:
    return f'{round(value):d} mm' if value is not None else ''


def _when(iso: str) -> str:
    at = datetime.fromisoformat(iso.replace('Z', '+00:00')) + LIMA
    return f'el {DAYS[at.weekday()]} {at.day} a las {at:%H:%M}'


def sentence(name: str, weather: dict | None, river: dict | None, satellite: dict | None,
             fires: dict | None) -> str:
    parts = []
    if weather and weather.get('rain_mm_7d') is not None:
        text = f'{_mm(weather["rain_mm_7d"])} de lluvia en 7 días'
        if weather.get('rain_mm_next_3d') is not None:
            text += f' y {_mm(weather["rain_mm_next_3d"])} previstos en 3 días'
        parts.append(text)
    discharge = (river or {}).get('discharge')
    if discharge:
        parts.append(f'{FLOW[discharge["trend"]]} ({round(discharge["today_m3s"]):,d} m³/s)'.replace(',', ' '))
    if fires and fires.get('count_7d'):
        n = fires['count_7d']
        parts.append(f'{n} foco{"s" if n != 1 else ""} de calor a menos de {round(fires["radius_km"])} km')
    passes = (satellite or {}).get('next_passes') or []
    if passes:
        parts.append(f'próximo paso de radar {_when(passes[0]["at"])}')
    if not parts:
        return f'Río {name}: sin datos recientes.'
    return f'Río {name}: {", ".join(parts)}.'


def build(slugs, names: dict, weather: dict, rivers: dict, satellite: dict, fires: dict) -> dict:
    return {slug: sentence(river_name(slug, names), weather.get(slug), rivers.get(slug), satellite.get(slug),
                           fires.get(slug))
            for slug in sorted(slugs)}
