from unittest.mock import patch

import pytest

from detections.models import Alert, Detection, SatelliteImage
from ongs.models import River

pytestmark = pytest.mark.django_db


def test_requires_bearer(post_detection, payload):
    resp = post_detection(payload, token=None)
    assert resp.status_code == 401
    assert resp.json()['type'] == 'not_authenticated'


def test_rejects_wrong_secret(post_detection, payload):
    assert post_detection(payload, token='nope').status_code in (401, 403)
    assert not SatelliteImage.objects.exists()


def test_alerts_every_member_of_the_ong(post_detection, payload, ong, sent):
    resp = post_detection(payload)

    assert resp.status_code == 201
    assert resp.json()['alerts'] == 2
    image = SatelliteImage.objects.get()
    assert image.gs_uri == 'gs://river-images/yaguas/2026-10-15T1042Z_s1.tif#1792271000'
    assert Detection.objects.get().confidence == 0.87

    assert {phone for phone, _, _ in sent} == {'51936282808', '51999888777'}
    phone, template, components = next(c for c in sent if c[0] == '51936282808')
    assert template == 'condorin_evento_v2'
    body = [p['text'] for p in components[1]['parameters']]
    assert body == ['María', '1 posible draga', 'Yaguas', '15 de octubre de 2026 a las 05:42', '-2.7706, -70.9512']
    alert = Alert.objects.get(member__phone=phone)
    assert components[2]['parameters'][0]['text'] == alert.token
    assert components[3]['parameters'][0]['text'] == alert.token  # Ver evento
    assert alert.status == Alert.Status.SENT and alert.wa_message_id


def test_same_idempotency_key_is_processed_once(post_detection, payload, ong, sent):
    post_detection(payload)
    again = post_detection(payload)

    assert again.status_code == 200
    assert again.json()['duplicate'] is True
    assert SatelliteImage.objects.count() == 1
    assert len(sent) == 2


def test_low_confidence_is_stored_without_alerting(post_detection, payload, ong, sent):
    payload['detections'][0]['confidence'] = 0.2
    assert post_detection(payload).status_code == 201
    assert Detection.objects.count() == 1
    assert not Alert.objects.exists() and not sent


def test_unknown_river_is_created_and_nobody_is_alerted(post_detection, payload, ong, sent):
    payload['image']['river'] = 'nanay'
    assert post_detection(payload).status_code == 201
    assert River.objects.filter(slug='nanay', name='Nanay').exists()
    assert not sent


def test_invalid_body_returns_field_errors(post_detection, payload):
    payload['detections'][0]['lat'] = 120
    resp = post_detection(payload)
    assert resp.status_code == 400
    assert resp.json()['type'] == 'validation_error'
    assert 'detections' in resp.json()['field_errors']


def test_failed_whatsapp_is_kept_for_retry(post_detection, payload, ong, monkeypatch):
    from core import whatsapp

    def boom(*args):
        raise whatsapp.WhatsAppError('(#131026) Message undeliverable')

    monkeypatch.setattr(whatsapp, 'send_template', boom)
    post_detection(payload)
    assert set(Alert.objects.values_list('status', flat=True)) == {Alert.Status.FAILED}


@pytest.mark.parametrize('email, expected', [
    ('detector@condorin.iam.gserviceaccount.com', 201),
    ('someone@else.iam.gserviceaccount.com', 401),
])
def test_google_id_token(post_detection, payload, email, expected):
    claims = {'email': email, 'email_verified': True}
    with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims):
        assert post_detection(payload, token='header.claims.signature').status_code == expected


def test_event_template_second_button_opens_the_event_page(post_detection, payload, ong, sent, settings):
    from detections.text import alert_template_definition
    settings.WA_ALERT_TEMPLATE = 'condorin_evento'
    post_detection(payload)
    _, template, components = sent[0]
    token = components[2]['parameters'][0]['text']
    assert template == 'condorin_evento' and components[3]['parameters'][0]['text'] == token
    buttons = next(c for c in alert_template_definition('h')['components'] if c['type'] == 'BUTTONS')['buttons']
    assert [b['text'] for b in buttons] == ['Crear expediente', 'Ver evento']
    assert buttons[1]['url'].endswith('/evento/{{1}}')
