"""The ONG's memory of a place (expedientes/memoria.py), against the local FIXTURE server, never the real one."""
import json

import pytest

from accounts.session import session_token
from detections.models import Alert, SatelliteImage
from expedientes import memoria
from ongs.models import Member, Ong

from .atomic_memory_fixture import start

pytestmark = pytest.mark.django_db

SECRET = 'panel-secret'
MARIA = '51936282808'


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.PANEL_API_SECRET = SECRET
    settings.DEFAULT_ONG_ID = 0
    settings.ALERTS_INLINE = True  # the writes run right after the commit instead of on a thread


@pytest.fixture
def memory(settings):
    server, state = start('fixture-key')
    settings.ATOMIC_MEMORY_ENABLED = True
    settings.ATOMIC_MEMORY_API_KEY = 'fixture-key'
    settings.ATOMIC_MEMORY_API_URL = f'http://127.0.0.1:{server.server_address[1]}'
    settings.ATOMIC_MEMORY_SUBJECT_PREFIX = 'condorin-test'
    settings.ATOMIC_MEMORY_TIMEOUT = 0.5
    yield state
    server.shutdown()
    server.server_close()


def scene(post_detection, payload, n, lat=-2.7706, lon=-70.9512):
    body = json.loads(json.dumps(payload))
    body['image']['object'] = f'yaguas/2026-10-{n:02d}T1042Z_s1.tif'
    body['image']['captured_at'] = f'2026-10-{n:02d}T10:42:00Z'
    body['detections'][0].update(lat=lat, lon=lon)
    assert post_detection(body, key=f'scene-{n}').status_code in (200, 201, 202)
    return SatelliteImage.objects.get(captured_at__day=n)


@pytest.fixture
def first(post_detection, payload, ong, sent):
    return scene(post_detection, payload, 1)


def decide(client, image, capture, status='false_positive', reason='sandbar', phone=MARIA):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {SECRET}', 'HTTP_X_CONDORIN_PHONE': phone}
    with capture(execute=True):
        resp = client.post(f'/api/v1/panel/incidentes/{image.pk}/triaje',
                           json.dumps({'status': status, 'reason': reason}), content_type='application/json', **headers)
    assert resp.status_code == 200
    return resp


def antecedentes(client, image, phone=MARIA):
    auth = {'HTTP_AUTHORIZATION': f'Bearer {session_token(phone, "code")}'}
    return client.get(f'/api/v1/me/incidentes/{image.pk}/antecedentes', **auth)


def test_a_decision_is_written_for_the_ong_without_personal_data(client, memory, first, ong,
                                                                 django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    (stored,) = memory.memories.values()
    assert stored['user_id'] == f'condorin-test:ong:{ong.pk}'
    assert stored['source_site'] == 'condorin-antecedentes'
    assert stored['metadata']['condorin_event'] == 'rechazada' and stored['metadata']['condorin_image'] == first.pk
    blob = json.dumps(stored)
    assert MARIA not in blob and 'María' not in blob


def test_a_nearby_scene_gets_the_earlier_decision_nearest_first(client, memory, first, post_detection, payload,
                                                                django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks, reason='sandbar')
    near = scene(post_detection, payload, 2, lat=-2.7806)  # about 1.1 km south
    body = antecedentes(client, near).json()
    assert body['enabled'] is True and len(body['antecedentes']) == 1
    item = body['antecedentes'][0]
    assert item['event'] == 'rechazada' and item['event_label'] == 'Marcada como no es una draga'
    assert 'Banco de arena' in item['text'] and item['image_id'] == first.pk
    assert 1.0 <= item['distance_km'] <= 1.3


def test_a_far_scene_gets_nothing(client, memory, first, post_detection, payload, django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    far = scene(post_detection, payload, 2, lat=-2.9706)  # about 22 km away
    assert antecedentes(client, far).json()['antecedentes'] == []


def test_an_undone_decision_stops_being_an_antecedente(client, memory, first, post_detection, payload,
                                                       django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    near = scene(post_detection, payload, 2, lat=-2.7806)
    client.delete(f'/api/v1/panel/incidentes/{first.pk}/triaje', HTTP_AUTHORIZATION=f'Bearer {SECRET}',
                  HTTP_X_CONDORIN_PHONE=MARIA)
    assert antecedentes(client, near).json()['antecedentes'] == []
    # A different decision: only the memory that matches what the ONG decided now is shown, not the old rejection.
    decide(client, first, django_capture_on_commit_callbacks, status='confirmed', reason='')
    assert [a['event'] for a in antecedentes(client, near).json()['antecedentes']] == ['confirmada']


def test_the_scene_itself_is_not_its_own_antecedente(client, memory, first, django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    assert antecedentes(client, first).json()['antecedentes'] == []


def test_another_ong_does_not_see_them(client, memory, first, post_detection, payload, river,
                                       django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    other = Ong.objects.create(name='Otra ONG')
    other.rivers.add(river)
    Member.objects.create(ong=other, full_name='Ana', phone='51922333444')
    near = scene(post_detection, payload, 2, lat=-2.7806)
    assert antecedentes(client, near, phone='51922333444').json()['antecedentes'] == []


def test_a_filing_is_remembered(client, memory, first, post_detection, payload, django_capture_on_commit_callbacks):
    from expedientes.models import Authority, Expediente, Filing

    expediente = Expediente.objects.get(image=first)
    authority = Authority.objects.filter(active=True).first() or Authority.objects.create(
        code='fema', name='Fiscalía (FEMA)', kind='fiscalia')
    filing = Filing.objects.create(expediente=expediente, authority=authority, receipt_number='123-2026',
                                   filed_at='2026-10-20')
    memoria.record(expediente.ong, first, 'presentada', memoria.filing_text(filing))
    near = scene(post_detection, payload, 2, lat=-2.7806)
    item = antecedentes(client, near).json()['antecedentes'][0]
    assert item['event'] == 'presentada' and '123-2026' in item['text']


def test_the_expediente_link_shows_them_too(client, memory, first, post_detection, payload,
                                            django_capture_on_commit_callbacks):
    decide(client, first, django_capture_on_commit_callbacks)
    scene(post_detection, payload, 2, lat=-2.7806)
    alert = Alert.objects.filter(image__captured_at__day=2, member__phone=MARIA).get()
    body = client.get(f'/api/v1/expedientes/{alert.token}/antecedentes').json()
    assert body['enabled'] is True and body['antecedentes'][0]['event'] == 'rechazada'


def test_off_means_nothing_is_written_or_read(client, first, post_detection, payload, settings,
                                              django_capture_on_commit_callbacks):
    settings.ATOMIC_MEMORY_ENABLED = False
    decide(client, first, django_capture_on_commit_callbacks)
    assert antecedentes(client, first).json() == {'enabled': False, 'antecedentes': []}


def test_a_failed_write_never_breaks_the_decision(client, memory, first, django_capture_on_commit_callbacks):
    memory.fail_status = 503
    decide(client, first, django_capture_on_commit_callbacks)
    assert memory.memories == {}


def test_an_unreachable_memory_is_said_not_guessed(client, memory, first):
    memory.fail_status = 503
    resp = antecedentes(client, first)
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'


def test_the_panel_says_whether_antecedentes_are_on(client, first, settings):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {SECRET}', 'HTTP_X_CONDORIN_PHONE': MARIA}
    assert client.get('/api/v1/panel', **headers).json()['features'] == {'antecedentes': False}
    settings.ATOMIC_MEMORY_ENABLED, settings.ATOMIC_MEMORY_API_KEY = True, 'fixture-key'
    assert client.get('/api/v1/panel', **headers).json()['features'] == {'antecedentes': True}
