"""Link sign in for the static SPA, and every browser route working from condorin.pe."""
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import session
from detections.models import Alert
from expedientes import codes
from expedientes.tests.test_expediente import COMPLETE

pytestmark = pytest.mark.django_db

ORIGINS = ['https://condorin.pe', 'https://www.condorin.pe']


@pytest.fixture(autouse=True)
def _demo(settings):
    settings.DEFAULT_ONG_ID = 0


@pytest.fixture
def maria(post_detection, payload, ong, sent):
    post_detection(payload)
    return Alert.objects.get(member__phone='51936282808')


def link_sign_in(client, token):
    return client.post('/api/v1/auth/enlace', json.dumps({'token': token}), content_type='application/json')


# Link sign in

def test_link_signs_in_for_seven_days(client, maria):
    resp = link_sign_in(client, maria.token)
    assert resp.status_code == 200
    body = resp.json()
    assert body['via'] == 'link'
    assert body['member'] == {'name': 'María Huamán Ríos', 'phone': '51936282808'}
    assert body['ong'] == {'name': 'Amazonía Viva'}
    assert session.read_session(body['token']) == ('51936282808', 'link')
    me = client.get('/api/v1/me', HTTP_AUTHORIZATION=f'Bearer {body["token"]}')
    assert me.status_code == 200 and me.json()['member']['phone'] == '51936282808'


@pytest.mark.parametrize('change', [
    {'status': Alert.Status.PANEL},
    {'status': Alert.Status.FAILED},
    {'sent_at': timezone.now() - timedelta(days=8)},
    {'expires_at': timezone.now() - timedelta(minutes=1)},
])
def test_link_refused_with_the_same_404(client, maria, change):
    Alert.objects.filter(pk=maria.pk).update(**change)
    resp = link_sign_in(client, maria.token)
    assert resp.status_code == 404
    assert resp.json()['message'] == link_sign_in(client, 'unknown').json()['message']


def test_link_session_lasts_less_than_a_code_session(maria, monkeypatch):
    link, code = session.session_token(maria.member.phone, 'link'), session.session_token(maria.member.phone)
    monkeypatch.setattr(session, 'LINK_SESSION_SECONDS', -1)
    assert session.read_session(link) is None
    assert session.read_session(code) == ('51936282808', 'code')


def test_unknown_via_is_rejected(db):
    forged = session.signing.TimestampSigner(salt='session').sign_object({'p': '51936282808', 'via': 'admin'})
    assert session.read_session(forged) is None


def test_link_session_cannot_finalize_without_the_code(client, maria, monkeypatch, rf):
    token = link_sign_in(client, maria.token).json()['token']
    auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
    request = rf.get('/', **auth)
    with pytest.raises(session.SessionInvalid):
        session.require_session(request, allow_link=False)

    url = f'/api/v1/expedientes/{maria.token}'
    client.patch(url, json.dumps(COMPLETE), content_type='application/json', **auth)
    # The bearer is ignored by /enviar: without the WhatsApp code nothing is finalized.
    resp = client.post(f'{url}/enviar', json.dumps({'code': '000000'}), content_type='application/json', **auth)
    assert resp.status_code == 400 and resp.json()['type'] == 'code_expired'
    monkeypatch.setattr(codes.secrets, 'randbelow', lambda n: 123456)
    assert client.post(f'{url}/enviar', '{}', content_type='application/json', **auth).status_code == 202
    assert client.post(f'{url}/enviar', json.dumps({'code': '123456'}),
                       content_type='application/json', **auth).status_code == 200


# CORS from the static SPA

def preflight(client, path, origin, method, headers='authorization,content-type'):
    return client.options(path, HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
                          HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers)


@pytest.mark.parametrize('origin', ORIGINS)
def test_expediente_routes_from_the_browser(client, maria, origin, monkeypatch):
    url = f'/api/v1/expedientes/{maria.token}'
    for path, method in [(url, 'PATCH'), (url, 'GET'), (f'{url}/enviar', 'POST'),
                         (f'/api/v1/eventos/{maria.token}', 'GET')]:
        resp = preflight(client, path, origin, method)
        assert resp.status_code == 200, path
        assert resp['Access-Control-Allow-Origin'] == origin
        assert method in resp['Access-Control-Allow-Methods']
        allowed = resp['Access-Control-Allow-Headers'].lower()
        assert 'authorization' in allowed and 'content-type' in allowed

    assert client.get(url, HTTP_ORIGIN=origin)['Access-Control-Allow-Origin'] == origin
    assert client.get(f'/api/v1/eventos/{maria.token}', HTTP_ORIGIN=origin)['Access-Control-Allow-Origin'] == origin
    patched = client.patch(url, json.dumps({'rep_position': 'Presidenta'}), content_type='application/json',
                           HTTP_ORIGIN=origin)
    assert patched.status_code == 200 and patched['Access-Control-Allow-Origin'] == origin
    monkeypatch.setattr(codes.secrets, 'randbelow', lambda n: 123456)
    client.patch(url, json.dumps(COMPLETE), content_type='application/json')
    sent = client.post(f'{url}/enviar', '{}', content_type='application/json', HTTP_ORIGIN=origin)
    assert sent.status_code == 202 and sent['Access-Control-Allow-Origin'] == origin

    pdf = client.get(f'{url}?formato=pdf', HTTP_ORIGIN=origin)
    assert pdf.status_code == 200 and pdf['Content-Type'] == 'application/pdf'
    assert pdf['Access-Control-Allow-Origin'] == origin
    assert 'content-disposition' in pdf['Access-Control-Expose-Headers'].lower()
    assert pdf['Content-Disposition'].startswith('inline; filename=')


@pytest.mark.parametrize('origin', ORIGINS)
@pytest.mark.parametrize('path, method', [
    ('/api/v1/auth/codigo', 'POST'), ('/api/v1/auth/entrar', 'POST'), ('/api/v1/auth/enlace', 'POST'),
    ('/api/v1/me', 'GET'), ('/api/v1/me/incidentes/1/expediente', 'POST'),
])
def test_session_routes_from_the_browser(client, db, origin, path, method):
    resp = preflight(client, path, origin, method)
    assert resp.status_code == 200
    assert resp['Access-Control-Allow-Origin'] == origin


def test_other_origins_are_not_allowed(client, maria):
    resp = preflight(client, f'/api/v1/expedientes/{maria.token}', 'https://evil.example', 'PATCH')
    assert 'Access-Control-Allow-Origin' not in resp
