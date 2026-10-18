import gzip
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from fuentes import services
from fuentes.models import FeedCache
from fuentes.sources import REGISTRY, TILE_LAYERS, firms, openmeteo, sentinel

pytestmark = pytest.mark.django_db

TOP_KEYS = {'generated_at', 'sources', 'fires', 'satellite', 'weather', 'tile_layers', 'rivers', 'fires_near_rivers',
            'summary'}
SOURCE_KEYS = {'fetched_at', 'ok', 'ttl_s', 'error', 'attribution', 'url'}

FIRE = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-70.1, -12.9]},
        'properties': {'at': '2026-10-17T18:00:00Z', 'frp': 12.3, 'confidence': 'n', 'sensor': 'VIIRS',
                       'daynight': 'D'}}
SAT = {'s1_last': '2026-10-13T23:08:19Z', 's1_last_id': 'S1C_IW_GRDH_X', 's1_passes_30d': 8,
       's1_next_estimate': '2026-10-18T10:14:04Z', 's2_last': '2026-10-17T14:57:31Z', 's2_last_cloud': 93.2,
       's2_clear_last_30d': 4}
WEATHER = {'rain_mm_7d': 42.1, 'rain_mm_24h': 3.2, 'temp_c': 29.1, 'updated_at': '2026-10-18T05:00:00Z'}


@pytest.fixture
def fake_fetch(monkeypatch, settings):
    """Every source fetch replaced by a canned payload; counts the calls."""
    settings.FUENTES_INLINE = True
    settings.FUENTES_CACHE_SECONDS = 0
    calls = []
    canned = {
        'firms': {'fires': {'type': 'FeatureCollection', 'features': [FIRE]}, 'in_bbox': 1},
        'sentinel': {'rivers': {'malinowski': SAT}},
        'open-meteo': {'rivers': {'malinowski': WEATHER}},
        'glofas': {'rivers': {'malinowski': {'discharge': None}}},
    }
    for source_id, module in REGISTRY.items():
        def fetch(meter=None, source_id=source_id):
            calls.append(source_id)
            return dict(canned[source_id])
        monkeypatch.setattr(module, 'fetch', fetch)
    return calls


def fresh_rows():
    for source_id, module in REGISTRY.items():
        services.refresh(source_id, force=True)


def test_payload_shape(client, fake_fetch):
    fresh_rows()
    fake_fetch.clear()
    resp = client.get('/api/v1/fuentes')
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == TOP_KEYS
    assert set(body['sources']) == {'firms', 'sentinel', 'open-meteo', 'glofas'}
    for entry in body['sources'].values():
        assert set(entry) == SOURCE_KEYS and entry['ok'] is True and entry['error'] is None
    assert body['fires']['features'] == [FIRE]
    assert body['satellite'] == {'malinowski': SAT}
    assert body['weather'] == {'malinowski': WEATHER}
    assert body['tile_layers'] == TILE_LAYERS
    assert all({'id', 'title', 'url', 'attribution', 'min_zoom', 'max_zoom', 'opacity'} <= set(t) for t in TILE_LAYERS)
    assert fake_fetch == []  # everything fresh: no refresh


def test_empty_cache_answers_at_once_and_refreshes(client, fake_fetch):
    body = client.get('/api/v1/fuentes').json()
    assert body['fires']['features'] == [] and body['sources']['firms']['ok'] is False
    assert sorted(fake_fetch) == ['firms', 'glofas', 'open-meteo', 'sentinel']
    assert FeedCache.objects.filter(ok=True).count() == 4


def test_stale_row_triggers_one_refresh(client, fake_fetch):
    fresh_rows()
    FeedCache.objects.filter(source='firms').update(fetched_at=timezone.now() - timedelta(hours=2))
    fake_fetch.clear()
    client.get('/api/v1/fuentes')
    assert fake_fetch == ['firms']
    assert timezone.now() - FeedCache.objects.get(source='firms').fetched_at < timedelta(minutes=1)


def test_live_claim_on_another_instance_skips_refresh(client, fake_fetch):
    fresh_rows()
    FeedCache.objects.filter(source='firms').update(fetched_at=timezone.now() - timedelta(hours=2),
                                                     refreshing_since=timezone.now() - timedelta(minutes=1))
    fake_fetch.clear()
    client.get('/api/v1/fuentes')
    assert fake_fetch == []
    assert services.claim('firms') is False
    FeedCache.objects.filter(source='firms').update(refreshing_since=timezone.now() - timedelta(minutes=6))
    assert services.claim('firms') is True  # a dead claim is taken over


def test_failed_fetch_keeps_the_old_payload(client, fake_fetch, monkeypatch):
    fresh_rows()
    old = FeedCache.objects.get(source='firms')

    def boom(meter=None):
        raise TimeoutError('upstream slow')
    monkeypatch.setattr(firms, 'fetch', boom)
    row = services.refresh('firms', force=True)
    assert row.ok is False and 'upstream slow' in row.error
    assert row.payload == old.payload and row.fetched_at == old.fetched_at
    assert row.refreshing_since is not None  # backs off for the claim timeout
    body = client.get('/api/v1/fuentes').json()
    assert body['fires']['features'] == [FIRE]
    assert body['sources']['firms']['ok'] is False and 'upstream slow' in body['sources']['firms']['error']


def test_cors_gzip_cache_headers_and_etag(client, fake_fetch):
    fresh_rows()
    resp = client.get('/api/v1/fuentes', HTTP_ACCEPT_ENCODING='gzip, br', HTTP_ORIGIN='https://example.org')
    assert resp.status_code == 200
    assert resp['Access-Control-Allow-Origin'] == '*'
    assert resp['Content-Encoding'] == 'gzip'
    assert resp['Cache-Control'] == 'public, max-age=300, stale-while-revalidate=3600'
    assert 'Accept-Encoding' in resp['Vary']
    assert gzip.decompress(resp.content).startswith(b'{"generated_at"')
    again = client.get('/api/v1/fuentes', HTTP_IF_NONE_MATCH=resp['ETag'])
    assert again.status_code == 304
    preflight = client.options('/api/v1/fuentes', HTTP_ORIGIN='https://example.org',
                               HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET')
    assert preflight.status_code == 204 and preflight['Access-Control-Allow-Origin'] == '*'


def test_refresh_command(fake_fetch, capsys):
    call_command('refresh_fuentes')
    assert sorted(fake_fetch) == ['firms', 'glofas', 'open-meteo', 'sentinel']
    call_command('refresh_fuentes')  # all fresh now
    assert len(fake_fetch) == 4
    call_command('refresh_fuentes', '--source', 'firms', '--force')
    assert fake_fetch[-1] == 'firms'
    assert '1 fires kept of 1 in bbox' in capsys.readouterr().out


# Pure parsing, no database needed beyond the marker.

CSV = '\n'.join([
    'latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight',
    '5.58228,-53.63139,329.73,0.7,0.75,2026-10-16,0421,N,nominal,2.0NRT,288.21,5.24,N',      # Guyana: out
    '-12.95001,-69.95002,330.1,0.4,0.4,2026-10-16,1805,N,high,2.0NRT,290.0,30.5,D',          # in
    '-12.95003,-69.95004,331.1,0.4,0.4,2026-10-16,1806,N,nominal,2.0NRT,290.0,12.0,D',       # same spot and day
    '-3.7,-73.4,320.0,0.4,0.4,2026-10-17,0610,N,low,2.0NRT,290.0,2.5,N',                    # in
    '-3.7,-73.4,320.0,0.4,0.4,2026-10-01,0610,N,low,2.0NRT,290.0,9.5,N',                    # too old
    '-20.0,-70.0,320.0,0.4,0.4,2026-10-17,0610,N,low,2.0NRT,290.0,9.5,N',                   # south: out
    '-10.0,-67.5,320.0,0.4,0.4,2026-10-17,0610,N,low,2.0NRT,290.0,9.5,N',                   # Brazil: out
    'broken,row',
])


def test_firms_bbox_age_and_dedupe():
    since = datetime(2026, 10, 11, tzinfo=UTC)
    fires = firms.parse_rows(CSV.splitlines(), since)
    assert [(f['lat'], f['frp']) for f in fires] == [(-12.95, 30.5), (-12.95, 12.0), (-3.7, 2.5)]
    picked = firms.select(fires)
    assert [f['frp'] for f in picked] == [2.5, 30.5]  # deduped, newest first
    assert firms.select(fires, limit=1)[0]['frp'] == 30.5  # the cap keeps the hottest
    feature = firms.to_feature(picked[1])
    assert feature['geometry']['coordinates'] == [-69.95, -12.95]
    assert feature['properties'] == {'at': '2026-10-16T18:05:00Z', 'frp': 30.5, 'confidence': 'h',
                                     'sensor': 'VIIRS', 'daynight': 'D'}


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self, chunk_size=None):
        yield from self.body.splitlines()

    def iter_content(self, chunk_size=None):
        yield self.body


def test_firms_fetch_streams_and_caps(monkeypatch):
    seen = []

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            seen.append((url, kwargs['timeout'], self.headers.get('User-Agent')))
            return FakeResponse(CSV.encode())
    monkeypatch.setattr('fuentes.http._session', lambda: type('S', (Session,), {'headers': {
        'User-Agent': 'OjoDeCondor/1.0 (+https://condorin.pe)'}})())
    monkeypatch.setattr(firms.timezone, 'now', lambda: datetime(2026, 10, 18, tzinfo=UTC))
    data = firms.fetch()
    assert len(seen) == 3 and all(t == (5, 15) and ua.startswith('OjoDeCondor/1.0') for _, t, ua in seen)
    assert data['in_bbox'] == 9 and len(data['fires']['features']) == 2  # the same rows from 3 satellites


def product(name, start, **attrs):
    return {'name': name, 'start': datetime.fromisoformat(start), 'attrs': attrs}


def test_sentinel1_passes_and_next_estimate():
    now = datetime(2026, 10, 18, 3, 0, tzinfo=UTC)
    products = [
        product('S1C_A', '2026-10-13T23:08:19+00:00', platformSerialIdentifier='C', orbitNumber=9872,
                relativeOrbitNumber=149),
        product('S1C_B', '2026-10-12T10:14:04+00:00', platformSerialIdentifier='C', orbitNumber=9850,
                relativeOrbitNumber=25),
        product('S1C_B2', '2026-10-12T10:14:29+00:00', platformSerialIdentifier='C', orbitNumber=9850,
                relativeOrbitNumber=25),  # next slice of the same datatake
        product('S1D_B', '2026-10-06T10:14:14+00:00', platformSerialIdentifier='D', orbitNumber=4893,
                relativeOrbitNumber=25),
        product('S1C_A0', '2026-10-01T23:08:19+00:00', platformSerialIdentifier='C', orbitNumber=9697,
                relativeOrbitNumber=149),
    ]
    out = sentinel.summarize_s1(products, now)
    assert out['s1_passes_30d'] == 4
    assert out['s1_last'] == '2026-10-13T23:08:19Z' and out['s1_last_id'] == 'S1C_A'
    # orbit 25 has two platforms (6 days): 10-12 + 6 = 10-18 10:14 (slice 2); orbit 149 alone: 10-25.
    assert out['s1_next_estimate'] == '2026-10-18T10:14:29Z'
    late = sentinel.summarize_s1(products, datetime(2026, 10, 30, tzinfo=UTC))
    assert late['s1_next_estimate'] == '2026-10-30T10:14:29Z'  # rolled forward past missed passes
    assert sentinel.summarize_s1([], now) == {'s1_last': None, 's1_last_id': None, 's1_passes_30d': 0,
                                              's1_next_estimate': None, 'next_passes': []}


def test_sentinel2_cloud_summary():
    products = [
        product('S2A_X1', '2026-10-17T14:57:31+00:00', cloudCover=93.22),
        product('S2A_X2', '2026-10-17T14:57:31+00:00', cloudCover=40.0),  # same pass, other tile
        product('S2B_Y', '2026-10-10T14:57:29+00:00', cloudCover=13.9),
        product('S2C_Z', '2026-09-27T14:47:29+00:00', cloudCover=9.4),
        product('S2C_W', '2026-09-25T14:47:29+00:00', cloudCover=60.6),
    ]
    assert sentinel.summarize_s2(products) == {'s2_last': '2026-10-17T14:57:31Z', 's2_last_cloud': 40.0,
                                               's2_clear_last_30d': 2}


def test_openmeteo_rain_windows():
    hours = [datetime(2026, 10, 10, tzinfo=UTC) + timedelta(hours=h) for h in range(8 * 24)]
    location = {'current': {'time': '2026-10-17T12:00', 'temperature_2m': 29.1},
                'hourly': {'time': [h.strftime('%Y-%m-%dT%H:%M') for h in hours],
                           'precipitation': [1.0] * len(hours)}}
    out = openmeteo.summarize(location)
    assert out == {'rain_mm_7d': 168.0, 'rain_mm_24h': 24.0, 'temp_c': 29.1, 'updated_at': '2026-10-17T12:00:00Z',
                   'forecast': [], 'rain_mm_next_3d': None}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    services._running.clear()
