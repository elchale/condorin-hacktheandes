"""One point per watched river: the centroid of its detections, else the fallback table of the map."""
from django.db.models import Avg

from detections.models import Detection
from mapa.builder import RIVER_FALLBACK
from ongs.models import River


def river_points() -> list[tuple[str, float, float]]:
    """[(slug, lat, lon)] for every river in the table plus the watched rivers of the fallback table."""
    centroids = {
        row['image__river__slug']: (float(row['lat']), float(row['lon']))
        for row in Detection.objects.values('image__river__slug').annotate(lat=Avg('lat'), lon=Avg('lon'))
    }
    points = []
    slugs = set(River.objects.values_list('slug', flat=True))
    slugs |= {slug for slug in RIVER_FALLBACK if slug.isascii()}  # 'marañon' is only a spelling of 'maranon'
    for slug in sorted(slugs):
        lat, lon = centroids.get(slug) or RIVER_FALLBACK.get(slug, (None, None))
        if lat is not None:
            points.append((slug, round(lat, 4), round(lon, 4)))
    return points
