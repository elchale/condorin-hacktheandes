"""Anyone may sign in and watch (the demo), but a number nobody invited joins as an observer: it sees the panel,
the incidents and the alerts, and never opens, edits, signs or files an expediente, nor reads the signer's data."""
import json

import pytest

from accounts.models import Admin
from detections.models import Alert
from expedientes.models import Expediente
from ongs.models import Member

pytestmark = pytest.mark.django_db

SECRET = 'panel-secret'
NEWCOMER = '51911222333'


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.PANEL_API_SECRET = SECRET
    settings.DEFAULT_ONG_ID = 0
    settings.DEFAULT_ONG_JOIN_ROLE = 'observer'


def panel(client, method, path, phone=NEWCOMER, data=None):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {SECRET}', 'HTTP_X_CONDORIN_PHONE': phone}
    if method == 'get':
        return client.get(path, **headers)
    return client.post(path, json.dumps(data or {}), content_type='application/json', **headers)


@pytest.fixture
def scene(post_detection, payload, ong, sent):
    """A scene with its automatic draft, signed by the ONG's legal representative (personal data inside)."""
    Member.objects.filter(phone='51936282808').update(
        dni='40506070', is_legal_representative=True, position='Presidenta')
    post_detection(payload)
    return Alert.objects.first().image


@pytest.fixture
def observer_token(client, scene):
    panel(client, 'get', '/api/v1/panel')  # joins the default ONG
    resp = panel(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente')
    assert resp.status_code == 200  # the link to read the incident and the draft
    return resp.json()['token']


def test_observer_sees_the_panel_and_the_incidents(client, scene):
    body = panel(client, 'get', '/api/v1/panel').json()
    assert body['member']['role'] == 'observer' and body['member']['can_act'] is False
    assert [i['id'] for i in body['incidents']] == [scene.pk]
    assert body['incidents'][0]['expediente']['status'] == 'draft'


def test_observer_reads_the_draft_without_personal_data(client, observer_token):
    resp = client.get(f'/api/v1/expedientes/{observer_token}')
    assert resp.status_code == 200
    body = resp.json()
    assert body['read_only'] is True and body['member']['can_act'] is False
    exp = body['expediente']
    assert exp['rep_name'] == exp['rep_dni'] == exp['rep_position'] == exp['notify_email'] == ''
    assert exp['created_by'] is None and exp['updated_by'] is None and exp['pdf_url'] is None
    assert exp['facts']  # the incident itself is there
    stored = Expediente.objects.get()
    assert stored.rep_dni == '40506070' and stored.updated_by is None  # reading changed nothing
    assert '40506070' not in resp.content.decode()


@pytest.mark.parametrize('request_', [
    ('patch', '', {'facts': 'otra cosa'}),
    ('patch', '', {'filings': [{'authority': 'fema', 'receipt_number': 'X', 'filed_at': '2026-10-18'}]}),
    ('post', '/enviar', {}),
    ('post', '/enviar', {'code': '123456'}),
    ('get', '?formato=pdf', None),
])
def test_observer_cannot_change_send_or_download(client, observer_token, sent, request_):
    method, suffix, data = request_
    url = f'/api/v1/expedientes/{observer_token}{suffix}'
    if method == 'get':
        resp = client.get(url)
    else:
        resp = getattr(client, method)(url, json.dumps(data), content_type='application/json')
    assert resp.status_code == 403
    assert resp.json()['type'] == 'observer_restricted'
    assert all(template != 'condorin_codigo' for _, template, _ in sent)  # no code went out
    assert Expediente.objects.get().facts != 'otra cosa'


def test_observer_event_page_hides_who_edited(client, scene, observer_token, settings):
    maria = Alert.objects.get(member__phone='51936282808')
    client.patch(f'/api/v1/expedientes/{maria.token}', json.dumps({'rep_position': 'Directora'}),
                 content_type='application/json')
    event = client.get(f'/api/v1/eventos/{observer_token}').json()
    assert event['expediente']['updated_by'] is None and event['member']['role'] == 'observer'
    row = panel(client, 'get', '/api/v1/panel').json()['incidents'][0]
    assert row['expediente']['updated_by'] is None
    # A real member still sees it.
    assert panel(client, 'get', '/api/v1/panel', phone='51936282808').json()['incidents'][0][
        'expediente']['updated_by'] == 'María Huamán Ríos'


def test_observer_without_a_draft_is_told_so(client, observer_token):
    Expediente.objects.all().delete()
    resp = client.get(f'/api/v1/expedientes/{observer_token}')
    assert resp.status_code == 403 and resp.json()['type'] == 'observer_restricted'
    assert not Expediente.objects.exists()  # an observer never creates one


def test_promoted_observer_gets_full_rights(client, observer_token):
    Member.objects.filter(phone=NEWCOMER).update(role=Member.Role.MEMBER)
    resp = client.patch(f'/api/v1/expedientes/{observer_token}', json.dumps({'rep_position': 'Vocal'}),
                        content_type='application/json')
    assert resp.status_code == 200 and resp.json()['read_only'] is False


def test_an_admin_joins_with_full_rights(client, scene):
    Admin.objects.create(email='carlos@example.org', name='Carlos', phone=NEWCOMER)
    from ongs.team import sync_internal_team
    sync_internal_team()
    body = panel(client, 'get', '/api/v1/panel').json()
    assert body['member']['role'] == 'member' and body['member']['can_act'] is True
