"""An ONG's decision on an incident (real, not a dredge, verified in the field), shared by its members."""
import json

import pytest
from django.core.management import call_command

from accounts.session import session_token
from detections.models import Alert, Triage
from expedientes.models import Expediente
from ongs.models import Member, Ong

pytestmark = pytest.mark.django_db

SECRET = 'panel-secret'
MARIA = '51936282808'
JOSE = '51999888777'


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.PANEL_API_SECRET = SECRET
    settings.DEFAULT_ONG_ID = 0


@pytest.fixture
def scene(post_detection, payload, ong, sent):
    post_detection(payload)
    return Alert.objects.first().image


def panel(client, method, path, phone=MARIA, data=None):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {SECRET}', 'HTTP_X_CONDORIN_PHONE': phone}
    if method == 'get':
        return client.get(path, **headers)
    return getattr(client, method)(path, json.dumps(data or {}), content_type='application/json', **headers)


def triage_url(scene):
    return f'/api/v1/panel/incidentes/{scene.pk}/triaje'


def incident(client, phone=MARIA):
    return panel(client, 'get', '/api/v1/panel', phone=phone).json()['incidents'][0]


def test_a_new_incident_has_no_triage(client, scene):
    body = panel(client, 'get', '/api/v1/panel').json()
    assert body['incidents'][0]['triage'] is None
    assert body['totals']['triage'] == {'new': 1, 'confirmed': 0, 'false_positive': 0, 'verified_field': 0}


def test_confirming_is_shared_with_the_whole_ong(client, scene):
    resp = panel(client, 'post', triage_url(scene), data={'status': 'confirmed'})
    assert resp.status_code == 200 and resp.json()['triage']['status'] == 'confirmed'
    seen = incident(client, phone=JOSE)['triage']  # another member of the ONG
    assert seen['status'] == 'confirmed' and seen['status_label'] == 'Es una draga'
    assert seen['set_by'] == 'María Huamán Ríos'
    assert Triage.objects.count() == 1


def test_last_decision_wins_and_keeps_one_row(client, scene):
    panel(client, 'post', triage_url(scene), data={'status': 'confirmed'})
    panel(client, 'post', triage_url(scene), phone=JOSE, data={'status': 'verified_field'})
    assert Triage.objects.get().status == 'verified_field'
    assert incident(client)['triage']['set_by'] == 'José Pérez'


def test_rejecting_needs_a_reason(client, scene):
    resp = panel(client, 'post', triage_url(scene), data={'status': 'false_positive'})
    assert resp.status_code == 400 and 'reason' in resp.json()['field_errors']
    resp = panel(client, 'post', triage_url(scene), data={'status': 'false_positive', 'reason': 'nonsense'})
    assert resp.status_code == 400
    assert not Triage.objects.exists()


def test_unknown_status_is_refused(client, scene):
    assert panel(client, 'post', triage_url(scene), data={'status': 'maybe'}).status_code == 400


def test_a_reason_is_dropped_unless_rejecting(client, scene):
    panel(client, 'post', triage_url(scene), data={'status': 'confirmed', 'reason': 'boat'})
    assert Triage.objects.get().reason == ''


def test_rejecting_takes_the_incident_out_of_the_work_to_do(client, scene):
    before = panel(client, 'get', '/api/v1/panel').json()['totals']
    assert before['draft'] == 1
    panel(client, 'post', triage_url(scene), data={'status': 'false_positive', 'reason': 'boat'})
    body = panel(client, 'get', '/api/v1/panel').json()
    assert body['totals']['incidents'] == 1 and body['totals']['draft'] == 0
    assert body['totals']['without_expediente'] == 0
    assert body['totals']['triage']['false_positive'] == 1 and body['totals']['triage']['new'] == 0
    assert body['incidents'][0]['triage']['reason_label'] == 'Bote o lancha'
    assert Expediente.objects.count() == 1  # nothing is deleted
    # Undoing the rejection brings the draft back.
    assert panel(client, 'delete', triage_url(scene)).json() == {'triage': None}
    assert panel(client, 'get', '/api/v1/panel').json()['totals']['draft'] == 1


def test_rejected_incident_without_a_draft_leaves_without_expediente(client, scene):
    Expediente.objects.all().delete()
    assert panel(client, 'get', '/api/v1/panel').json()['totals']['without_expediente'] == 1
    panel(client, 'post', triage_url(scene), data={'status': 'false_positive', 'reason': 'sandbar'})
    assert panel(client, 'get', '/api/v1/panel').json()['totals']['without_expediente'] == 0


def test_rejected_incident_cannot_be_opened_from_the_panel_until_restored(client, scene):
    panel(client, 'post', triage_url(scene), data={'status': 'false_positive', 'reason': 'other'})
    resp = panel(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente')
    assert resp.status_code == 409 and resp.json()['type'] == 'triage_rejected'
    panel(client, 'post', triage_url(scene), data={'status': 'confirmed'})
    assert panel(client, 'post', f'/api/v1/panel/incidentes/{scene.pk}/expediente').status_code == 200


def test_clearing_is_idempotent(client, scene):
    assert panel(client, 'delete', triage_url(scene)).status_code == 200
    assert panel(client, 'delete', triage_url(scene)).status_code == 200


def test_observers_see_the_decision_but_cannot_make_it(client, scene, settings):
    settings.DEFAULT_ONG_JOIN_ROLE = 'observer'
    panel(client, 'post', triage_url(scene), data={'status': 'confirmed'})
    newcomer = '51911222333'
    resp = panel(client, 'post', triage_url(scene), phone=newcomer, data={'status': 'confirmed'})
    assert resp.status_code == 403 and resp.json()['type'] == 'observer_restricted'
    assert panel(client, 'delete', triage_url(scene), phone=newcomer).status_code == 403
    seen = incident(client, phone=newcomer)['triage']
    assert seen['status'] == 'confirmed' and seen['set_by'] is None  # never who


def test_other_ongs_incidents_are_not_found(client, scene):
    other = Ong.objects.create(name='Otra ONG')
    Member.objects.create(ong=other, full_name='Ana', phone='51922333444')
    resp = panel(client, 'post', triage_url(scene), phone='51922333444', data={'status': 'confirmed'})
    assert resp.status_code == 404
    assert not Triage.objects.exists()


def test_two_ongs_decide_separately(client, scene, river):
    other = Ong.objects.create(name='Otra ONG')
    other.rivers.add(river)
    Member.objects.create(ong=other, full_name='Ana', phone='51922333444')
    panel(client, 'post', triage_url(scene), data={'status': 'confirmed'})
    panel(client, 'post', triage_url(scene), phone='51922333444',
          data={'status': 'false_positive', 'reason': 'boat'})
    assert Triage.objects.count() == 2
    assert incident(client)['triage']['status'] == 'confirmed'


def test_the_spa_session_routes(client, scene):
    auth = {'HTTP_AUTHORIZATION': f'Bearer {session_token(MARIA, "code")}'}
    url = f'/api/v1/me/incidentes/{scene.pk}/triaje'
    resp = client.post(url, json.dumps({'status': 'false_positive', 'reason': 'sandbar'}),
                       content_type='application/json', **auth)
    assert resp.status_code == 200 and resp.json()['triage']['reason'] == 'sandbar'
    me = client.get('/api/v1/me', **auth).json()
    assert me['incidents'][0]['triage']['status'] == 'false_positive'
    assert me['totals']['triage']['false_positive'] == 1
    assert client.delete(url, **auth).json() == {'triage': None}
    assert client.post(url, '{}', content_type='application/json').status_code in (401, 403)


def test_export_false_positives(client, scene, capsys):
    panel(client, 'post', triage_url(scene), data={'status': 'false_positive', 'reason': 'boat'})
    call_command('export_false_positives', '--compact')
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1 and rows[0]['reason'] == 'boat' and rows[0]['river'] == 'yaguas'
    assert rows[0]['detections'][0]['confidence'] > 0
