import json
from datetime import timedelta

import pytest
from django.utils import timezone

from detections.models import Alert
from expedientes.models import Expediente
from ongs.models import Member, Ong

pytestmark = pytest.mark.django_db

SECRET = 'panel-secret'


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.PANEL_API_SECRET = SECRET
    settings.DEFAULT_ONG_ID = 0


@pytest.fixture
def scene(post_detection, payload, ong, sent):
    post_detection(payload)
    return Alert.objects.first().image


def call(client, method, path, phone='51936282808', secret=SECRET, data=None):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {secret}'}
    if phone:
        headers['HTTP_X_CONDORIN_PHONE'] = phone
    if method == 'get':
        return client.get(path, **headers)
    return client.post(path, json.dumps(data or {}), content_type='application/json', **headers)


def test_requires_the_secret(client, ong):
    assert call(client, 'get', '/api/v1/panel', secret='').status_code == 403
    assert call(client, 'get', '/api/v1/panel', secret='wrong').status_code == 403


def test_panel_off_without_secret(client, ong, settings):
    settings.PANEL_API_SECRET = ''
    assert call(client, 'get', '/api/v1/panel', secret='anything').status_code == 403


def test_lists_the_ong_incidents(client, scene):
    body = call(client, 'get', '/api/v1/panel').json()
    assert body['member']['name'] == 'María Huamán Ríos'
    assert body['member']['joined_now'] is False
    assert body['ong']['name'] == 'Amazonía Viva'
    assert body['totals'] == {'incidents': 1, 'without_expediente': 0, 'draft': 1, 'ready': 0, 'filed': 0}
    incident = body['incidents'][0]
    assert incident['id'] == scene.pk
    assert incident['river']['name'] == 'Yaguas'
    assert incident['detections'] == 1
    assert incident['crops'] == []  # GCS is offline in tests
    assert incident['expediente']['status_label'] == 'Borrador listo para revisar'


def test_new_person_joins_the_default_ong(client, scene):
    body = call(client, 'get', '/api/v1/panel', phone='51911222333').json()
    assert body['member'] == {'name': '', 'phone': '51911222333', 'joined_now': True}
    assert body['totals']['incidents'] == 1
    member = Member.objects.get(phone='51911222333')
    assert member.ong.name == 'Asociación Amazonía Viva'
    assert call(client, 'get', '/api/v1/panel', phone='51911222333').json()['member']['joined_now'] is False


def test_default_ong_setting(client, ong, settings):
    other = Ong.objects.create(name='Otra ONG')
    settings.DEFAULT_ONG_ID = other.pk
    call(client, 'get', '/api/v1/panel', phone='51911222333')
    assert Member.objects.get(phone='51911222333').ong == other


def test_deactivated_member_is_not_rejoined(client, ong):
    Member.objects.filter(phone='51999888777').update(active=False)
    assert call(client, 'get', '/api/v1/panel', phone='51999888777').status_code == 403


def test_open_expediente_from_panel(client, scene):
    newcomer = '51911222333'
    call(client, 'get', '/api/v1/panel', phone=newcomer)
    res = call(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente', phone=newcomer)
    assert res.status_code == 200
    alert = Alert.objects.get(token=res.json()['token'])
    # Joining sends no event, so the panel opens the expediente with a fresh (never sent) alert.
    assert alert.member.phone == newcomer and Alert.objects.filter(member=alert.member).count() == 1

    # The token opens the shared expediente; the newcomer's name is asked there and remembered.
    page = client.get(f'/api/v1/expedientes/{alert.token}').json()
    assert 'rep_name' in page['expediente']['missing']
    client.patch(f'/api/v1/expedientes/{alert.token}', json.dumps({'rep_name': 'Rosa Inuma'}),
                 content_type='application/json')
    assert Member.objects.get(phone=newcomer).full_name == 'Rosa Inuma'

    # Same token next time, and the panel now shows the draft.
    again = call(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente', phone=newcomer)
    assert again.json()['token'] == alert.token
    incident = call(client, 'get', '/api/v1/panel', phone=newcomer).json()['incidents'][0]
    assert incident['expediente']['status'] == Expediente.Status.DRAFT
    assert incident['expediente']['updated_by'] == 'Rosa Inuma'


def test_panel_alerts_are_never_sent(client, scene, sent):
    from django.core.management import call_command
    # A member added by hand (not through the panel join) gets no welcome alert.
    Member.objects.create(ong=Ong.objects.get(internal=False), full_name='Rosa Inuma', phone='51911222333')
    call(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente', phone='51911222333')
    assert Alert.objects.get(member__phone='51911222333').status == Alert.Status.PANEL
    before = len(sent)
    call_command('send_pending_alerts')
    assert len(sent) == before


def test_cannot_open_another_ongs_scene(client, scene):
    other = Ong.objects.create(name='Otra ONG')
    Member.objects.create(ong=other, full_name='Ana', phone='51955444333')
    assert call(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente',
                phone='51955444333').status_code == 404


def test_link_signs_in_the_member_it_was_sent_to(client, scene):
    alert = Alert.objects.get(member__phone='51936282808')
    assert alert.status == Alert.Status.SENT
    res = call(client, 'post', '/api/v1/panel/enlace', phone=None, data={'token': alert.token})
    assert res.json() == {'phone': '51936282808', 'name': 'María Huamán Ríos', 'ong': 'Amazonía Viva'}


def test_link_sign_in_needs_the_secret(client, scene):
    alert = Alert.objects.first()
    assert call(client, 'post', '/api/v1/panel/enlace', phone=None, secret='',
                data={'token': alert.token}).status_code == 403


@pytest.mark.parametrize('change', [
    {'status': Alert.Status.PANEL},
    {'status': Alert.Status.FAILED},
    {'sent_at': timezone.now() - timedelta(days=8)},
    {'expires_at': timezone.now() - timedelta(minutes=1)},
])
def test_link_sign_in_refused(client, scene, change):
    alert = Alert.objects.get(member__phone='51936282808')
    Alert.objects.filter(pk=alert.pk).update(**change)
    res = call(client, 'post', '/api/v1/panel/enlace', phone=None, data={'token': alert.token})
    assert res.status_code == 404


def test_link_sign_in_unknown_token(client, ong):
    assert call(client, 'post', '/api/v1/panel/enlace', phone=None, data={'token': 'nope'}).status_code == 404


def test_new_member_gets_only_the_welcome(client, scene, sent, settings, django_capture_on_commit_callbacks):
    settings.ALERTS_INLINE = True
    with django_capture_on_commit_callbacks(execute=True):
        call(client, 'get', '/api/v1/panel', phone='51911222333')
    assert sent[-1] == ('51911222333', 'condorin_bienvenida', [])
    # No event: joining never creates or sends an alert.
    assert not Alert.objects.filter(member__phone='51911222333').exists()

    # Only on joining: later visits do not resend it.
    before = len(sent)
    with django_capture_on_commit_callbacks(execute=True):
        call(client, 'get', '/api/v1/panel', phone='51911222333')
    assert len(sent) == before
