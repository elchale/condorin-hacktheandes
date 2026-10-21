"""Field notes in Atomic Memory, against the local FIXTURE server (atomic_memory_fixture.py), never the real one."""
import json

import pytest

from detections.models import Alert
from expedientes.models import Expediente
from ongs.models import Member

from .atomic_memory_fixture import start

pytestmark = pytest.mark.django_db

NOTE = 'Acceso por la quebrada Lobo, dos horas en peque peque desde la comunidad Santa Lucía.'


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


@pytest.fixture
def alerts(post_detection, payload, ong, sent):
    post_detection(payload)
    return {a.member.phone: a for a in Alert.objects.select_related('member')}


@pytest.fixture
def maria(alerts):
    return alerts['51936282808']


@pytest.fixture
def jose(alerts):
    return alerts['51999888777']


def session(phone, via='code'):
    from accounts.session import session_token

    return {'HTTP_AUTHORIZATION': f'Bearer {session_token(phone, via)}'}


def notes_url(alert, note_id=''):
    return f'/api/v1/expedientes/{alert.token}/notas' + (f'/{note_id}' if note_id else '')


def list_notes(client, alert, **headers):
    return client.get(notes_url(alert), **(headers or session(alert.member.phone)))


def save_note(client, alert, text=NOTE, **headers):
    return client.post(notes_url(alert), json.dumps({'text': text}), content_type='application/json',
                       **(headers or session(alert.member.phone)))


def later_scene(post_detection, payload):
    """A second scene on the same river, so the member opens a new expediente."""
    body = json.loads(json.dumps(payload))
    body['image'].update({'object': 'yaguas/2026-10-16T1042Z_s1.tif', 'generation': '1792272000',
                          'captured_at': '2026-10-16T10:42:00Z'})
    post_detection(body, key='river-images/yaguas/2026-10-16T1042Z_s1.tif#1792272000')
    return Alert.objects.filter(member__phone='51936282808').order_by('-pk').first()


def test_off_by_default_and_nothing_is_called(client, maria, settings):
    assert settings.ATOMIC_MEMORY_ENABLED is False
    resp = list_notes(client, maria)
    assert resp.status_code == 200 and resp.json() == {'enabled': False, 'notes': []}
    assert save_note(client, maria).json()['type'] == 'notes_disabled'
    # The expediente itself is untouched by the feature.
    assert client.get(f'/api/v1/expedientes/{maria.token}').status_code == 200


def test_enabled_without_a_key_stays_off(client, maria, memory, settings):
    settings.ATOMIC_MEMORY_API_KEY = ''
    assert list_notes(client, maria).json()['enabled'] is False
    assert memory.requests == []


def test_a_saved_note_comes_back_on_the_next_expediente(client, maria, memory, post_detection, payload):
    resp = save_note(client, maria)
    assert resp.status_code == 201
    note = resp.json()['note']
    assert note['text'] == NOTE and note['river'] == 'yaguas' and note['id']

    ingest = memory.requests[-1]
    assert ingest['path'] == '/v1/memories/ingest/quick'
    assert ingest['authorization'] == 'Bearer fixture-key'
    assert ingest['body']['user_id'] == f'condorin-test:member:{maria.member.pk}'
    assert ingest['body']['skip_extraction'] is True and 'session_id' not in ingest['body']
    assert ingest['body']['metadata']['condorin_expediente'] == Expediente.objects.get().pk

    newer = later_scene(post_detection, payload)
    assert newer.pk != maria.pk and newer.image_id != maria.image_id
    resp = list_notes(client, newer)
    assert resp.status_code == 200
    assert resp.json() == {'enabled': True, 'notes': [{**note, 'created_at': resp.json()['notes'][0]['created_at']}]}
    search = memory.requests[-1]
    assert search['path'] == '/v1/memories/search/fast'
    assert search['body']['user_id'] == f'condorin-test:member:{maria.member.pk}'
    assert 'Yaguas' in search['body']['query'] and search['body']['limit'] == 5


def test_a_note_never_changes_the_expediente(client, maria, memory):
    client.get(f'/api/v1/expedientes/{maria.token}')
    before = Expediente.objects.values().get()
    assert save_note(client, maria).status_code == 201
    after = Expediente.objects.values().get()
    assert before == after


def test_no_phone_or_name_leaves_the_server(client, maria, memory):
    save_note(client, maria)
    list_notes(client, maria)
    sent = json.dumps([r['body'] for r in memory.requests] + [r['query'] for r in memory.requests])
    assert maria.member.phone not in sent and 'María' not in sent


@pytest.mark.parametrize('who', ['none', 'link', 'other', 'forged'])
def test_notes_need_a_code_session_of_that_same_member(client, maria, memory, who):
    headers = {
        'none': {},
        'link': session(maria.member.phone, 'link'),
        'other': session('51999888777'),
        'forged': {'HTTP_AUTHORIZATION': 'Bearer forged'},
    }[who]
    for resp in (client.get(notes_url(maria), **headers),
                 client.post(notes_url(maria), {'text': NOTE}, content_type='application/json', **headers)):
        assert resp.status_code == 403 and resp.json()['type'] == 'notes_session_required'
    assert memory.requests == []


def test_another_member_never_sees_or_deletes_my_notes(client, maria, jose, memory):
    mine = save_note(client, maria).json()['note']
    resp = list_notes(client, jose)
    assert resp.status_code == 200 and resp.json()['notes'] == []
    # Even knowing the id, José's subject cannot reach it.
    assert client.delete(notes_url(jose, mine['id']), **session(jose.member.phone)).status_code == 404
    assert client.patch(notes_url(jose, mine['id']), json.dumps({'text': 'cambiada'}),
                        content_type='application/json', **session(jose.member.phone)).status_code == 404
    assert [n['text'] for n in list_notes(client, maria).json()['notes']] == [NOTE]


def test_the_same_phone_in_another_ong_is_another_subject(client, maria, memory, ong, river):
    from ongs.models import Ong

    other = Ong.objects.create(name='Otra ONG')
    other_row = Member.objects.create(ong=other, full_name='María Huamán Ríos', phone=maria.member.phone)
    from expedientes import notas

    assert notas.subject(other_row) != notas.subject(maria.member)


def test_correcting_a_note_replaces_it(client, maria, memory):
    old = save_note(client, maria).json()['note']
    resp = client.patch(notes_url(maria, old['id']), json.dumps({'text': 'Acceso por la quebrada Tigre.'}),
                        content_type='application/json', **session(maria.member.phone))
    assert resp.status_code == 200
    body = resp.json()
    assert body['previous_deleted'] is True and body['note']['text'] == 'Acceso por la quebrada Tigre.'
    assert body['note']['id'] != old['id'] and body['note']['river'] == 'yaguas'
    assert [n['text'] for n in list_notes(client, maria).json()['notes']] == ['Acceso por la quebrada Tigre.']


def test_a_correction_says_so_when_the_old_note_could_not_be_deleted(client, maria, memory):
    old = save_note(client, maria).json()['note']
    memory.fail_delete = True
    resp = client.patch(notes_url(maria, old['id']), json.dumps({'text': 'Acceso por la quebrada Tigre.'}),
                        content_type='application/json', **session(maria.member.phone))
    assert resp.status_code == 200 and resp.json()['previous_deleted'] is False
    assert len(memory.memories) == 2


def test_deleting_a_note(client, maria, memory):
    note = save_note(client, maria).json()['note']
    resp = client.delete(notes_url(maria, note['id']), **session(maria.member.phone))
    assert resp.status_code == 200 and resp.json() == {'deleted': True}
    assert list_notes(client, maria).json()['notes'] == []
    assert memory.requests[-2]['method'] == 'DELETE'
    assert memory.requests[-2]['query'] == {'user_id': f'condorin-test:member:{maria.member.pk}'}


def test_a_note_id_that_is_not_a_uuid_never_reaches_the_service(client, maria, memory):
    resp = client.delete(notes_url(maria, '..%2F..%2Fadmin'), **session(maria.member.phone))
    assert resp.status_code == 404
    assert memory.requests == []


@pytest.mark.parametrize('text', ['   ', 42, ['nota'], {'t': 'nota'}, None, True, 'x' * 501])
def test_a_note_that_is_not_text_or_too_long_is_refused_not_cut(client, maria, memory, text):
    resp = client.post(notes_url(maria), json.dumps({'text': text}), content_type='application/json',
                       **session(maria.member.phone))
    assert resp.status_code == 400 and 'text' in resp.json()['field_errors']
    assert memory.requests == []


def test_a_note_of_exactly_the_limit_is_kept_whole(client, maria, memory):
    resp = save_note(client, maria, '  ' + 'x' * 500 + '\n')
    assert resp.status_code == 201 and resp.json()['note']['text'] == 'x' * 500


def test_a_correction_that_is_too_long_is_refused(client, maria, memory):
    old = save_note(client, maria).json()['note']
    calls = len(memory.requests)
    resp = client.patch(notes_url(maria, old['id']), json.dumps({'text': 'y' * 501}),
                        content_type='application/json', **session(maria.member.phone))
    assert resp.status_code == 400 and 'text' in resp.json()['field_errors']
    assert len(memory.requests) == calls and len(memory.memories) == 1


@pytest.mark.parametrize('failure', ['status', 'timeout', 'nothing_stored', 'down'])
def test_a_failing_service_never_reports_a_saved_note(client, maria, memory, settings, failure):
    if failure == 'status':
        memory.fail_status = 503
    elif failure == 'timeout':
        memory.delay = 2
    elif failure == 'nothing_stored':
        memory.store_nothing = True
    else:
        settings.ATOMIC_MEMORY_API_URL = 'http://127.0.0.1:9'  # nothing listens there
    resp = save_note(client, maria)
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'
    assert 'no se guardó' in resp.json()['message']
    assert memory.memories == {}
    # The expediente keeps working.
    assert client.get(f'/api/v1/expedientes/{maria.token}').status_code == 200


def test_a_failing_search_does_not_break_the_page(client, maria, memory):
    memory.fail_status = 500
    resp = list_notes(client, maria)
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'
    assert client.get(f'/api/v1/expedientes/{maria.token}').status_code == 200


def test_the_key_is_wrong(client, maria, memory, settings):
    settings.ATOMIC_MEMORY_API_KEY = 'another-key'
    assert save_note(client, maria).status_code == 503


def test_observers_have_no_notes(client, maria, memory):
    Member.objects.filter(pk=maria.member.pk).update(role=Member.Role.OBSERVER)
    resp = list_notes(client, maria)
    assert resp.status_code == 403 and resp.json()['type'] == 'observer_restricted'
    assert memory.requests == []


def test_results_this_app_did_not_write_are_ignored(client, maria, memory):
    import uuid

    memory.memories['x'] = {'id': str(uuid.uuid4()), 'user_id': f'condorin-test:member:{maria.member.pk}',
                            'content': 'Nota de campo sobre el río Yaguas sin metadatos',
                            'source_site': 'condorin-notas-de-campo', 'metadata': {}, 'created_at': '2026'}
    assert list_notes(client, maria).json()['notes'] == []


def only(method, status, body, headers=None):
    """A fixture override answering `method` calls with this raw body."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return lambda m, path: (status, raw, headers or {}) if m == method else None


@pytest.mark.parametrize('answer', [
    {'success': False}, {}, {'success': 'true'}, {'success': 1}, [True], b'not json', b'',
])
def test_a_delete_counts_only_with_success_true(client, maria, memory, answer):
    note = save_note(client, maria).json()['note']
    memory.override = only('DELETE', 200, answer)
    resp = client.delete(notes_url(maria, note['id']), **session(maria.member.phone))
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'
    assert 'deleted' not in resp.json()
    memory.override = None
    assert [n['id'] for n in list_notes(client, maria).json()['notes']] == [note['id']]


def test_a_correction_whose_delete_is_not_confirmed_says_the_old_note_stays(client, maria, memory):
    old = save_note(client, maria).json()['note']
    memory.override = only('DELETE', 200, {'success': False})
    resp = client.patch(notes_url(maria, old['id']), json.dumps({'text': 'Acceso por la quebrada Tigre.'}),
                        content_type='application/json', **session(maria.member.phone))
    assert resp.status_code == 200 and resp.json()['previous_deleted'] is False


@pytest.mark.parametrize('answer', [
    {'stored_memory_ids': 'abc'}, {'stored_memory_ids': {'id': 'x'}}, {'stored_memory_ids': [123]},
    {'stored_memory_ids': ['not-a-uuid']}, {'stored_memory_ids': []}, {'stored_memory_ids': None}, {},
    {'stored_memory_ids': ['6f1c5b0e-8f6a-4a57-9a3e-0f8d2d6f1a11', '0b7a1f3c-2d4e-4f5a-8b6c-7d8e9f0a1b2c']},
    [], b'{"stored_memory_ids": ["6f1c5b0e', b'\xff\xfe',
])
def test_a_save_counts_only_with_one_valid_stored_id(client, maria, memory, answer):
    memory.override = only('POST', 200, answer)
    resp = save_note(client, maria)
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'
    assert 'note' not in resp.json()


@pytest.mark.parametrize('answer', [
    {'memories': 'x'}, {'memories': {'id': 1}}, {'memories': [1, 2]}, {'memories': None}, {}, [], b'<html>',
])
def test_a_malformed_search_is_an_error_not_an_empty_list(client, maria, memory, answer):
    memory.override = only('POST', 200, answer)
    resp = list_notes(client, maria)
    assert resp.status_code == 503 and resp.json()['type'] == 'notes_unavailable'


def test_our_rows_with_malformed_fields_are_skipped(client, maria, memory):
    good = save_note(client, maria).json()['note']
    row = {'id': 'not-a-uuid', 'content': 'Nota de campo sobre el río Yaguas',
           'metadata': {'condorin_kind': 'nota_de_campo', 'condorin_text': 'x', 'condorin_river': 'yaguas'}}
    bad_text = {**row, 'id': '6f1c5b0e-8f6a-4a57-9a3e-0f8d2d6f1a11',
                'metadata': {**row['metadata'], 'condorin_text': {'html': '<b>'}}}
    good_row = {**memory.memories[good['id']]}
    memory.override = only('POST', 200, {'memories': [row, bad_text, good_row]})
    assert [n['id'] for n in list_notes(client, maria).json()['notes']] == [good['id']]


def test_redirects_are_never_followed(client, maria, memory):
    memory.override = only('POST', 302, {}, {'Location': '/v1/memories/search/fast'})
    resp = save_note(client, maria)
    assert resp.status_code == 503
    assert len(memory.requests) == 1


def test_a_memory_row_with_its_embedding_is_read(client, maria, memory):
    """GET /v1/memories/{id} returns the whole row, embedding included (core-openapi getMemory)."""
    old = save_note(client, maria).json()['note']
    memory.memories[old['id']]['embedding'] = [0.0123456789012345] * 3072
    resp = client.patch(notes_url(maria, old['id']), json.dumps({'text': 'Acceso por la quebrada Tigre.'}),
                        content_type='application/json', **session(maria.member.phone))
    assert resp.status_code == 200 and resp.json()['previous_deleted'] is True


def test_a_huge_answer_is_not_read(client, maria, memory):
    memory.override = only('POST', 200, b'{"memories": [], "pad": "' + b'x' * (300 * 1024) + b'"}')
    assert list_notes(client, maria).status_code == 503


def test_a_404_on_search_is_unavailable_not_a_missing_note(client, maria, memory):
    memory.override = only('POST', 404, {'error': 'nope'})
    assert list_notes(client, maria).status_code == 503


@pytest.mark.parametrize('url, ok', [
    ('https://api.atomicstrata.ai', True),
    ('https://api.atomicstrata.ai/', True),
    ('http://127.0.0.1:4610', True),
    ('http://localhost:4610', True),
    ('http://api.atomicstrata.ai', False),
    ('http://localhost.evil.example', False),
    ('https://user:pass@api.atomicstrata.ai', False),
    ('https://api.atomicstrata.ai?x=1', False),
    ('ftp://api.atomicstrata.ai', False),
    ('api.atomicstrata.ai', False),
    ('', False),
])
def test_only_https_or_a_loopback_fixture(url, ok):
    from expedientes import notas

    if ok:
        assert notas.base_url(url).rstrip('/') == url.rstrip('/')
    else:
        with pytest.raises(notas.MemoryUnavailable):
            notas.base_url(url)


def test_a_plain_http_provider_is_never_called(client, maria, memory, settings):
    settings.ATOMIC_MEMORY_API_URL = 'http://api.atomicstrata.ai'
    resp = save_note(client, maria)
    assert resp.status_code == 503
    assert memory.requests == []


@pytest.mark.parametrize('value, expected', [
    (3, 3.0), ('2.5', 2.5), (0, 0.1), (-5, 0.1), (999, 10.0), (float('inf'), 10.0), (float('nan'), 10.0),
    ('slow', 10.0), (None, 10.0),
])
def test_the_timeout_is_always_bounded(settings, value, expected):
    from expedientes import notas

    settings.ATOMIC_MEMORY_TIMEOUT = value
    assert notas.timeout() == expected
