import gzip
import io
import json

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.session import session_token
from detections.models import Alert
from expedientes.models import Expediente

pytestmark = pytest.mark.django_db

TOP_KEYS = {'generated_at', 'clock', 'brand', 'bbox', 'totals', 'rivers', 'images', 'detections', 'timeline', 'activity', 'mine'}
TOTAL_KEYS = {'images', 'detections', 'alerting_detections', 'alerts_sent', 'alerts_opened', 'expedientes',
              'expedientes_filed', 'ongs', 'members', 'users', 'rivers'}


@pytest.fixture
def scene(post_detection, payload, ong, sent):
    payload['detections'].append({'lat': -2.7801, 'lon': -70.9620, 'confidence': 0.31, 'bbox': [1, 2, 3, 4]})
    post_detection(payload)
    return Alert.objects.first().image


def test_payload_shape(client, scene):
    # The automatic draft is silent until a member edits it.
    Expediente.objects.update(updated_by=scene.alerts.first().member)
    resp = client.get('/api/v1/mapa')
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == TOP_KEYS
    assert body['brand'] == 'Ojo de Cóndor'
    assert set(body['totals']) == TOTAL_KEYS
    assert body['totals'] == {
        'images': 1, 'detections': 2, 'alerting_detections': 1, 'alerts_sent': 2, 'alerts_opened': 0,
        'expedientes': 1, 'expedientes_filed': 0, 'ongs': 1, 'members': 2, 'users': 0, 'rivers': 1,
    }
    river = body['rivers'][0]
    assert river['slug'] == 'yaguas' and river['ongs'] == 1 and river['detections'] == 2
    assert -2.79 < river['lat'] < -2.77  # centroid of its detections, not the fallback
    image = body['images'][0]
    assert image['id'] == scene.pk and image['alerting'] == 1 and image['top_confidence'] == 0.87
    assert image['expedientes'] == {'draft': 1, 'ready': 0, 'filed': 0}
    features = body['detections']['features']
    assert [f['properties']['alerting'] for f in features] == [True, False]
    # Rounded to 3 decimals (about 110 m) on the public map; the panel keeps the exact point.
    assert features[0]['geometry'] == {'type': 'Point', 'coordinates': [-70.951, -2.771]}
    assert features[0]['properties']['kind'] == 'draga'
    minlon, minlat, maxlon, maxlat = body['bbox']
    assert minlon < -70.96 < maxlon and minlat < -2.78 < maxlat
    assert body['timeline'] == [{'month': '2026-10', 'images': 1, 'detections': 2}]
    kinds = {a['kind'] for a in body['activity']}
    assert kinds == {'image', 'alert', 'expediente_opened'}
    assert body['mine'] is None


def test_never_leaks_people_or_links(client, scene):
    text = client.get('/api/v1/mapa').content.decode()
    for secret in ('María', '51936282808', Alert.objects.first().token, 'gs://', 'https://storage'):
        assert secret not in text


def test_empty_database_still_answers(client, db):
    body = client.get('/api/v1/mapa').json()
    assert body['totals']['detections'] == 0
    assert body['detections']['features'] == []
    yaguas = body['rivers'][0]
    assert (yaguas['lat'], yaguas['lon']) == (-2.65, -71.35)  # fallback table


def test_query_count_does_not_grow(client, scene, post_detection, payload, settings):
    settings.MAPA_CACHE_SECONDS = 0
    with CaptureQueriesContext(connection) as one:
        client.get('/api/v1/mapa')
    payload['image']['captured_at'] = '2026-10-16T10:42:00Z'
    post_detection(payload, key='another-scene')
    with CaptureQueriesContext(connection) as two:
        client.get('/api/v1/mapa')
    assert len(two) == len(one) <= 9


def test_public_cache_cors_and_etag(client, scene):
    resp = client.get('/api/v1/mapa', HTTP_ORIGIN='https://ejemplo.org')
    assert resp['Cache-Control'] == 'public, max-age=60, stale-while-revalidate=600'
    assert resp['Access-Control-Allow-Origin'] == '*'
    assert 'Authorization' in resp['Vary']
    etag = resp['ETag']
    again = client.get('/api/v1/mapa', HTTP_IF_NONE_MATCH=etag)
    assert again.status_code == 304
    assert again['Access-Control-Allow-Origin'] == '*'


def test_preflight_from_any_origin(client, db):
    resp = client.options('/api/v1/mapa', HTTP_ORIGIN='https://ejemplo.org',
                          HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET', HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization')
    assert resp.status_code in (200, 204)
    assert resp['Access-Control-Allow-Origin'] == '*'
    assert 'Authorization' in resp['Access-Control-Allow-Headers']


def test_gzip(client, scene):
    raw = client.get('/api/v1/mapa')
    zipped = client.get('/api/v1/mapa', HTTP_ACCEPT_ENCODING='gzip')
    assert 'Content-Encoding' not in raw
    assert zipped['Content-Encoding'] == 'gzip'
    assert json.loads(gzip.decompress(zipped.content)) == raw.json()
    assert len(zipped.content) < len(raw.content)
    assert zipped['ETag'].startswith('W/')  # GZipMiddleware weakens it, and If-None-Match still matches
    assert client.get('/api/v1/mapa', HTTP_ACCEPT_ENCODING='gzip', HTTP_IF_NONE_MATCH=zipped['ETag']).status_code == 304


def test_expediente_routes_stay_private(client, scene):
    alert = Alert.objects.first()
    resp = client.get(f'/api/v1/expedientes/{alert.token}', HTTP_ACCEPT_ENCODING='gzip')
    assert resp.status_code == 200
    assert 'public' not in resp.get('Cache-Control', '')
    assert resp.get('Access-Control-Allow-Origin') != '*'


def test_signed_in_member_gets_mine(client, scene):
    resp = client.get('/api/v1/mapa', HTTP_AUTHORIZATION=f'Bearer {session_token("51936282808")}')
    mine = resp.json()['mine']
    assert mine == {'member': {'name': 'María Huamán Ríos', 'phone': '51936282808'},
                    'ong': {'name': 'Amazonía Viva', 'rivers': ['yaguas']}}
    assert resp['Cache-Control'].startswith('private')


def test_bad_bearer_is_just_anonymous(client, scene):
    resp = client.get('/api/v1/mapa', HTTP_AUTHORIZATION='Bearer forged')
    assert resp.status_code == 200
    assert resp.json()['mine'] is None


def test_export_command_prints_the_same_payload(client, scene):
    out = io.StringIO()
    call_command('export_mapa', stdout=out)
    printed = json.loads(out.getvalue())
    served = client.get('/api/v1/mapa').json()
    printed.pop('generated_at'), served.pop('generated_at')
    printed['clock'].pop('now'), served['clock'].pop('now')  # ticks between the two calls
    assert printed == served
