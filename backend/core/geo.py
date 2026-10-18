"""WGS84 to UTM, so the denuncia carries the coordinates the way Peruvian authorities read them."""
import math

_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)


def utm(lat: float, lon: float) -> dict:
    """Returns zone, hemisphere band, easting and northing in meters (WGS84 datum)."""
    zone = int((lon + 180) // 6) + 1
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi = math.radians(lat)
    lam = math.radians(lon)

    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * (lam - lon0)
    m = _A * (
        (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256) * phi
        - (3 * _E2 / 8 + 3 * _E2 ** 2 / 32 + 45 * _E2 ** 3 / 1024) * math.sin(2 * phi)
        + (15 * _E2 ** 2 / 256 + 45 * _E2 ** 3 / 1024) * math.sin(4 * phi)
        - (35 * _E2 ** 3 / 3072) * math.sin(6 * phi)
    )

    easting = _K0 * n * (
        a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t ** 2 + 72 * c - 58 * _EP2) * a ** 5 / 120
    ) + 500000.0
    northing = _K0 * (
        m + n * math.tan(phi) * (
            a ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a ** 4 / 24
            + (61 - 58 * t + t ** 2 + 600 * c - 330 * _EP2) * a ** 6 / 720
        )
    )
    if lat < 0:
        northing += 10000000.0

    return {
        'zone': zone,
        'hemisphere': 'S' if lat < 0 else 'N',
        'easting': round(easting),
        'northing': round(northing),
        'label': f'{zone}{"S" if lat < 0 else "N"} {round(easting)} E {round(northing)} N',
    }


def maps_url(lat: float, lon: float) -> str:
    return f'https://www.google.com/maps/search/?api=1&query={lat},{lon}'


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def coord(value) -> str:
    """-2.770600 → '-2.7706' (5 decimals is about one meter)."""
    return f'{float(value):.5f}'.rstrip('0').rstrip('.')
