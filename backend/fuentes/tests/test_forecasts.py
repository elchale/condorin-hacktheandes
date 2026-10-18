"""Forecasts, discharge, next radar passes, fires near rivers, the summary and the refresh endpoint."""
import threading
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from fuentes import services, summary
from fuentes.models import FeedCache
from fuentes.sources import REGISTRY, firms, glofas, openmeteo, sentinel

pytestmark = pytest.mark.django_db

SECRET = 'test-panel-secret'


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    services._running.clear()


def test_openmeteo_forecast_in_lima_time():
    days = [(datetime(2026, 10, 11) + timedelta(days=d)).strftime('%Y-%m-%d') for d in range(14)]
    location = {'utc_offset_seconds': -18000,
                'current': {'time': '2026-10-18T06:30', 'temperature_2m': 23.2},
                'hourly': {'time': ['2026-10-18T06:00', '2026-10-18T07:00'], 'precipitation': [2.0, 5.0]},
                'daily': {'time': days, 'precipitation_sum': [float(d) for d in range(14)],
                          'precipitation_probability_max': [50] * 14, 'temperature_2m_max': [31.5] * 14}}
    out = openmeteo.summarize(location)
    assert out['updated_at'] == '2026-10-18T11:30:00Z'  # 06:30 in Lima
    assert out['rain_mm_24h'] == 2.0  # 07:00 is still in the future
    assert [d['date'] for d in out['forecast']] == days[7:]
    assert out['forecast'][0] == {'date': '2026-10-18', 'rain_mm': 7.0, 'rain_prob': 50, 'tmax_c': 31.5}
    assert out['rain_mm_next_3d'] == 7.0 + 8.0 + 9.0


def flood(today_index, values, mean=100.0, lat=-2.775, lon=-70.85):
    days = [(datetime(2026, 10, 11) + timedelta(days=d)).strftime('%Y-%m-%d') for d in range(len(values))]
    return {'latitude': lat, 'longitude': lon,
            'daily': {'time': days, 'river_discharge': values, 'river_discharge_mean': [mean] * len(values)}}


def test_discharge_trend_and_series():
    rising = glofas.summarize(flood(7, [100.0] * 8 + [104.0, 108.0, 112.0] + [115.0] * 4), '2026-10-18')
    assert rising['today_m3s'] == 100.0 and rising['mean_m3s'] == 100.0 and rising['trend'] == 'sube'
    assert len(rising['series']) == 15 and rising['series'][0] == {'date': '2026-10-11', 'm3s': 100.0}
    assert rising['cell'] == [-2.775, -70.85]
    falling = glofas.summarize(flood(7, [200.0] * 8 + [150.0] * 7), '2026-10-18')
    assert falling['trend'] == 'baja'
    flat = glofas.summarize(flood(7, [200.0] * 8 + [204.0] * 7), '2026-10-18')
    assert flat['trend'] == 'estable'
    assert glofas.summarize(flood(7, [None] * 15), '2026-10-18') is None
    assert glofas.summarize(flood(7, [1.0] * 15), '2030-01-01') is None


def test_glofas_fetch_snaps_to_the_main_channel(monkeypatch):
    monkeypatch.setattr(glofas, 'river_points', lambda: [('yaguas', -2.7706, -70.9512)])
    monkeypatch.setattr(glofas, 'lima_today', lambda now=None: '2026-10-18')
    calls = []

    def get_json(url, params, **kwargs):
        calls.append(params)
        lats, lons = params['latitude'].split(','), params['longitude'].split(',')
        if 'past_days' not in params:  # the probe: the cell 0.1 degree east is the big river
            return [{'daily': {'river_discharge_mean': [164.4 if lon == '-70.8512' and lat == '-2.7706' else 3.0]}}
                    for lat, lon in zip(lats, lons, strict=True)]
        assert (lats, lons) == (['-2.7706'], ['-70.8512'])
        return [flood(7, [160.0] * 15, mean=164.4)]
    monkeypatch.setattr(glofas, 'get_json', get_json)
    data = glofas.fetch()
    assert len(calls) == 2 and len(calls[0]['latitude'].split(',')) == 25
    assert data['rivers']['yaguas']['discharge']['today_m3s'] == 160.0
    assert data['warnings'] == []


def product(name, start, serial, orbit, relative):
    return {'name': name, 'start': datetime.fromisoformat(start),
            'attrs': {'platformSerialIdentifier': serial, 'orbitNumber': orbit, 'relativeOrbitNumber': relative}}


def test_next_passes_alternate_platforms_on_shared_orbits():
    now = datetime(2026, 10, 18, 3, 0, tzinfo=UTC)
    products = [
        product('S1C_B', '2026-10-12T10:14:04+00:00', 'C', 9850, 25),
        product('S1D_B', '2026-10-06T10:14:14+00:00', 'D', 4893, 25),
        product('S1C_A', '2026-10-13T23:08:19+00:00', 'C', 9872, 149),
    ]
    out = sentinel.summarize_s1(products, now)
    assert out['next_passes'][:3] == [
        {'at': '2026-10-18T10:14:04Z', 'platform': 'Sentinel-1D'},  # orbit 25, 6 days, the other platform
        {'at': '2026-10-24T10:14:04Z', 'platform': 'Sentinel-1C'},
        {'at': '2026-10-25T23:08:19Z', 'platform': 'Sentinel-1C'},  # orbit 149 alone, 12 days
    ]
    assert len(out['next_passes']) == sentinel.STORED_PASSES
    assert out['s1_next_estimate'] == out['next_passes'][0]['at']


def fire(lat, lon, frp, at='2026-10-17T18:00:00+00:00'):
    return {'lat': lat, 'lon': lon, 'frp': frp, 'at': datetime.fromisoformat(at), 'confidence': 'n', 'daynight': 'D'}


def test_fires_near_rivers_dedupes_and_uses_25_km():
    fires = [fire(-2.70, -70.95, 10.0),                                      # about 8 km
             fire(-2.70, -70.95, 4.0),                                       # same spot, other satellite
             fire(-2.95, -70.95, 22.5, '2026-10-16T06:00:00+00:00'),         # about 20 km
             fire(-3.20, -70.95, 50.0)]                                      # about 48 km: out
    out = firms.near_rivers(fires, [('yaguas', -2.7706, -70.9512), ('nanay', -3.75, -73.45)])
    assert out['yaguas'] == {'count_7d': 2, 'max_frp': 22.5, 'last_at': '2026-10-17T18:00:00Z', 'radius_km': 25.0}
    assert out['nanay']['count_7d'] == 0 and out['nanay']['last_at'] is None
    assert firms.BBOX == (-78.5, -13.5, -68.0, 0.5) and firms.MAX_FIRES == 2000


def test_summary_sentence():
    text = summary.sentence(
        'Yaguas',
        {'rain_mm_7d': 33.2, 'rain_mm_next_3d': 12.4},
        {'discharge': {'today_m3s': 2442.3, 'trend': 'estable'}},
        {'next_passes': [{'at': '2026-10-20T23:02:00Z', 'platform': 'Sentinel-1C'}]},
        {'count_7d': 4, 'radius_km': 25.0})
    assert text == ('Río Yaguas: 33 mm de lluvia en 7 días y 12 mm previstos en 3 días, caudal estable '
                    '(2 442 m³/s), 4 focos de calor a menos de 25 km, próximo paso de radar el martes 20 a las 18:02.')
    assert ' - ' not in text and '—' not in text
    assert summary.sentence('Nanay', None, None, None, None) == 'Río Nanay: sin datos recientes.'
    assert summary.river_name('madre-de-dios', {}) == 'Madre de Dios'


@pytest.fixture
def canned(monkeypatch, settings):
    settings.FUENTES_INLINE = True
    settings.FUENTES_CACHE_SECONDS = 0
    settings.PANEL_API_SECRET = SECRET
    calls = []
    future = (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    past = (timezone.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    payloads = {
        'firms': {'fires': {'type': 'FeatureCollection', 'features': []},
                  'near_rivers': {'yaguas': {'count_7d': 1, 'max_frp': 3.0, 'last_at': past, 'radius_km': 25.0}}},
        'sentinel': {'rivers': {'yaguas': {'s1_next_estimate': past, 'next_passes': [
            {'at': past, 'platform': 'Sentinel-1C'}, {'at': future, 'platform': 'Sentinel-1D'}]}}},
        'open-meteo': {'rivers': {'yaguas': {'rain_mm_7d': 33.0, 'rain_mm_next_3d': 5.0, 'forecast': []}}},
        'glofas': {'rivers': {'yaguas': {'discharge': {'today_m3s': 160.0, 'mean_m3s': 164.4, 'trend': 'baja',
                                                       'series': []}}}},
    }
    for source_id, module in REGISTRY.items():
        def fetch(meter=None, source_id=source_id):
            calls.append(source_id)
            return dict(payloads[source_id])
        monkeypatch.setattr(module, 'fetch', fetch)
    return calls


def test_payload_has_the_new_keys_and_drops_past_passes(client, canned):
    for source_id in REGISTRY:
        services.refresh(source_id, force=True)
    body = client.get('/api/v1/fuentes').json()
    assert body['rivers']['yaguas']['discharge']['trend'] == 'baja'
    assert body['fires_near_rivers']['yaguas']['count_7d'] == 1
    assert [p['platform'] for p in body['satellite']['yaguas']['next_passes']] == ['Sentinel-1D']
    assert body['summary']['yaguas'].startswith('Río Yaguas: 33 mm de lluvia en 7 días y 5 mm previstos')
    assert 'caudal en bajada (160 m³/s)' in body['summary']['yaguas']


def post(client, secret=None, query=''):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {secret}'} if secret is not None else {}
    return client.post(f'/api/v1/fuentes/refresh{query}', **headers)


def test_refresh_endpoint_needs_the_panel_secret(client, canned):
    assert post(client).status_code == 403
    assert post(client, 'wrong').status_code == 403
    assert canned == []


def test_refresh_endpoint_refreshes_stale_then_forces(client, canned, monkeypatch):
    resp = post(client, SECRET)
    assert resp.status_code == 200
    assert {k: v['status'] for k, v in resp.json()['sources'].items()} == dict.fromkeys(REGISTRY, 'ok')
    assert sorted(canned) == sorted(REGISTRY)
    again = post(client, SECRET).json()['sources']
    assert {v['status'] for v in again.values()} == {'fresh'} and len(canned) == 4
    FeedCache.objects.filter(source='glofas').update(refreshing_since=timezone.now())  # another worker
    FeedCache.objects.filter(source='glofas').update(fetched_at=timezone.now() - timedelta(days=1))
    assert post(client, SECRET).json()['sources']['glofas']['status'] == 'busy'
    forced = post(client, SECRET, '?force=1').json()
    assert forced['force'] is True and {v['status'] for v in forced['sources'].values()} == {'ok'}
    assert len(canned) == 8

    def boom(meter=None):
        raise TimeoutError('slow')
    for module in REGISTRY.values():
        monkeypatch.setattr(module, 'fetch', boom)
    failed = post(client, SECRET, '?force=1')
    assert failed.status_code == 502 and failed.json()['sources']['firms']['error'] == 'TimeoutError: slow'


def test_refresh_due_reports_slow_sources_as_running(settings, monkeypatch):
    settings.FUENTES_INLINE = False
    gate = threading.Event()

    def fake(source_id, force):
        if source_id == 'firms':
            gate.wait(5)
        return FeedCache(source=source_id, ok=True, fetched_at=timezone.now(), duration_ms=5)
    monkeypatch.setattr(services, '_refresh_in_thread', fake)
    out = services.refresh_due(force=True, wait_s=0.5)
    gate.set()
    assert out['firms'] == {'status': 'running'}
    assert {out[s]['status'] for s in ('sentinel', 'open-meteo', 'glofas')} == {'ok'}


def test_refresh_endpoint_uses_its_own_secret_when_set(client, canned, settings):
    settings.PANEL_API_SECRET = SECRET
    settings.FUENTES_REFRESH_SECRET = 'feeds-only-secret'
    assert post(client, SECRET).status_code == 403  # the panel secret no longer refreshes
    assert post(client, 'feeds-only-secret').status_code in (200, 502)
