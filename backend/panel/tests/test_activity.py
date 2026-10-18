import pytest

from detections.models import Alert
from expedientes import codes
from expedientes.tests.test_expediente import finalize, patch

from .test_panel import SECRET, call

pytestmark = pytest.mark.django_db

URL = '/api/v1/panel/actividad'
KEYS = ['received', 'detections', 'evidence', 'routing', 'alerts', 'opened', 'expediente', 'filed']


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.PANEL_API_SECRET = SECRET


def feed(client, query=''):
    res = call(client, 'get', URL + query, phone=None)
    assert res.status_code == 200
    return res.json()


def states(event):
    return {s['key']: s['state'] for s in event['steps']}


def test_requires_the_secret(client, db):
    assert call(client, 'get', URL, phone=None, secret='').status_code == 403
    assert call(client, 'get', URL, phone=None, secret='wrong').status_code == 403


def test_alerted_event(client, post_detection, payload, ong, sent):
    post_detection(payload)
    body = feed(client)
    assert body['threshold'] == 0.5
    event = body['events'][0]
    assert event['decision'] == 'alerted'
    assert event['river']['name'] == 'Yaguas'
    assert event['scene'] == {'uri': 'gs://river-images/yaguas/2026-10-15T1042Z_s1.tif#1792271000', 'pinned': False}
    assert event['detections'][0] == {'index': 0, 'lat': '-2.7706', 'lon': '-70.9512', 'confidence': 0.87,
                                      'alerting': True, 'crop_url': None, 'pinned': False}
    assert [s['key'] for s in event['steps']] == KEYS
    assert states(event) == {
        'received': 'done', 'detections': 'done', 'evidence': 'pending', 'routing': 'done',
        'alerts': 'done', 'opened': 'pending', 'expediente': 'pending', 'filed': 'pending',
    }
    steps = {s['key']: s for s in event['steps']}
    assert steps['detections']['detail'] == 'La única detección supera el umbral de 50% (87%).'
    assert steps['routing']['detail'] == 'Lo vigila 1 ONG: Amazonía Viva (2 miembros).'
    assert steps['alerts']['detail'] == '2 alertas enviadas por WhatsApp.'
    assert steps['alerts']['at']
    assert not any(' - ' in s['detail'] or '—' in s['detail'] for s in event['steps'])

    viva = event['ongs'][0]
    assert viva['name'] == 'Amazonía Viva' and viva['members'] == 2
    # The automatic draft from ingest: there, but nobody opened it yet.
    assert viva['expediente']['status_label'] == 'Borrador listo para revisar'
    assert steps['opened']['detail'] == 'El borrador automático está listo, nadie lo abrió todavía.'
    assert {a['phone_hint'] for a in viva['alerts']} == {'+51 *** *** 808', '+51 *** *** 777'}
    assert {a['status'] for a in viva['alerts']} == {'sent'}
    assert event['authorities_suggested']


def test_below_threshold(client, post_detection, payload, ong, sent):
    payload['detections'][0]['confidence'] = 0.3
    post_detection(payload)
    event = feed(client)['events'][0]
    assert event['decision'] == 'below_threshold'
    assert event['detections'][0]['alerting'] is False
    assert event['ongs'][0]['alerts'] == []
    assert states(event)['routing'] == 'skipped'
    assert all(states(event)[k] == 'skipped' for k in KEYS[4:])
    assert 'Ninguna detección supera' in event['steps'][1]['detail']


def test_no_watchers(client, post_detection, payload, river, sent):
    post_detection(payload)
    event = feed(client)['events'][0]
    assert event['decision'] == 'no_watchers'
    assert event['ongs'] == []
    routing = event['steps'][3]
    assert routing['state'] == 'failed' and routing['detail'] == 'Ninguna ONG vigila el río Yaguas.'
    assert states(event)['alerts'] == 'skipped'
    assert not sent


def test_expediente_draft_then_confirmed(client, post_detection, payload, ong, sent, monkeypatch):
    monkeypatch.setattr(codes.secrets, 'randbelow', lambda n: 123456)
    post_detection(payload)
    maria = Alert.objects.get(member__phone='51936282808')
    client.get(f'/api/v1/expedientes/{maria.token}')

    event = feed(client)['events'][0]
    assert states(event)['opened'] == 'done'
    assert event['steps'][5]['detail'] == 'María Huamán Ríos abrió el expediente de Amazonía Viva.'
    assert event['steps'][6]['state'] == 'pending'
    assert event['steps'][6]['detail'].startswith('Borrador en curso, faltan')
    assert event['ongs'][0]['expediente']['status'] == 'draft'

    finalize(client, maria, '123456')
    event = feed(client)['events'][0]
    expediente = event['ongs'][0]['expediente']
    assert expediente['status'] == 'ready' and expediente['folio'].startswith('CND-')
    step = event['steps'][6]
    assert step['state'] == 'done' and step['at']
    assert step['detail'].startswith(f'{expediente["folio"]} confirmado con código de WhatsApp, para ')
    assert states(event)['filed'] == 'pending'

    patch(client, maria, {'filings': [{'authority': 'fema', 'receipt_number': '123', 'filed_at': '2026-10-18'}]})
    event = feed(client)['events'][0]
    filed = event['steps'][7]
    assert filed == {'key': 'filed', 'label': 'Denuncia presentada', 'state': 'done',
                     'detail': 'Presentado ante FEMA con el número 123.', 'at': '2026-10-18'}
    assert event['ongs'][0]['expediente']['filings'][0]['receipt_number'] == '123'


def test_limit_and_order(client, post_detection, payload, ong, sent):
    for i in range(3):
        payload['image']['object'] = f'yaguas/scene_{i}.tif'
        post_detection(payload, key=f'river-images/yaguas/scene_{i}.tif#1')
    events = feed(client, '?limit=2')['events']
    assert len(events) == 2
    assert events[0]['id'] > events[1]['id']
    assert events[0]['scene']['uri'].startswith('gs://river-images/yaguas/scene_2.tif')
    assert len(feed(client, '?limit=nope')['events']) == 3
    assert len(feed(client, '?limit=999')['events']) == 3
