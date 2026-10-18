import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from accounts.models import Admin
from detections.models import Alert
from expedientes import codes
from expedientes.models import Expediente
from ongs.models import Member, Ong

pytestmark = pytest.mark.django_db

COMPLETE = {
    'ong_address': 'Jr. Próspero 123, Iquitos',
    'notify_email': 'denuncias@amazoniaviva.org',
    'rep_dni': '12345678',
    'rep_position': 'Presidenta',
    'truth_declared': True,
}


@pytest.fixture
def alerts(post_detection, payload, ong, sent):
    post_detection(payload)
    return {a.member.phone: a for a in Alert.objects.select_related('member')}


@pytest.fixture
def maria(alerts):
    return alerts['51936282808']


@pytest.fixture
def fixed_code(monkeypatch):
    monkeypatch.setattr(codes.secrets, 'randbelow', lambda n: 123456)
    return '123456'


def url(alert, suffix=''):
    return f'/api/v1/expedientes/{alert.token}{suffix}'


def patch(client, alert, data):
    return client.patch(url(alert), json.dumps(data), content_type='application/json')


def send(client, alert, data=None):
    return client.post(url(alert, '/enviar'), data or {}, content_type='application/json')


def finalize(client, alert, code):
    patch(client, alert, COMPLETE)
    send(client, alert)
    return send(client, alert, {'code': code})


def test_unknown_token(client, db):
    assert client.get('/api/v1/expedientes/nope').status_code == 404


def test_expired_link(client, maria):
    Alert.objects.filter(pk=maria.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    resp = client.get(url(maria))
    assert resp.status_code == 410
    assert resp.json()['type'] == 'link_expired'


def test_first_tap_creates_a_prefilled_expediente(client, maria):
    data = client.get(url(maria)).json()

    exp = data['expediente']
    assert exp['status'] == 'draft'
    assert exp['ong_name'] == 'Asociación Amazonía Viva' and exp['ong_ruc'] == '20123456789'
    assert exp['rep_name'] == 'María Huamán Ríos'
    assert 'del río Yaguas' in exp['facts'] and 'Parque Nacional Yaguas' in exp['facts']
    assert exp['notify_email'] == 'maria@example.org'
    assert set(exp['missing']) == {'ong_address', 'rep_dni', 'truth_declared'}
    assert data['incident']['detections'][0]['utm'] == '19S 283090 E 9693584 N'
    assert {a['code'] for a in data['authorities'] if a['selected']} == {'fema', 'oefa', 'sernanp'}
    assert Alert.objects.get(pk=maria.pk).opened_at is not None
    # Everything else arrives written, so the member only reviews.
    assert exp['place_reference'].startswith('Río Yaguas') and '-2.7706, -70.9512' in exp['place_reference']
    assert exp['field_evidence_links'].startswith('https://www.google.com/maps/')
    assert exp['field_observations'] and exp['suspects'] == 'Por identificar.'
    assert 'mercurio' in exp['risk_notes'] and 'Parque Nacional Yaguas' in exp['risk_notes']


def test_first_tap_emails_the_admins_once(client, maria, django_capture_on_commit_callbacks):
    Admin.objects.create(email='carlos@example.org')
    Admin.objects.create(email='former@example.org', active=False)

    with django_capture_on_commit_callbacks(execute=True):
        client.get(url(maria))
        client.get(url(maria))
        patch(client, maria, {'rep_position': 'Presidenta'})

    assert len(mail.outbox) == 1
    opened = mail.outbox[0]
    assert opened.to == ['carlos@example.org']
    assert opened.subject == 'María Huamán Ríos de Amazonía Viva abrió un expediente en Ojo de Cóndor'
    assert 'río Yaguas' in opened.body and '+51936282808' in opened.body and '/admin/en-vivo' in opened.body


def test_event_page_and_no_admins_send_nothing(client, maria, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.get(f'/api/v1/eventos/{maria.token}')
        client.get(url(maria))
    assert mail.outbox == []


def test_member_without_dni_gets_the_legal_representative_as_signer(client, alerts):
    Member.objects.filter(phone='51936282808').update(
        is_legal_representative=True, dni='87654321', position='Presidenta')
    exp = client.get(url(alerts['51999888777'])).json()['expediente']
    assert (exp['rep_name'], exp['rep_dni'], exp['rep_position']) == ('María Huamán Ríos', '87654321', 'Presidenta')
    assert 'rep_dni' not in exp['missing']


def test_members_of_the_same_ong_share_one_expediente(client, alerts):
    first = client.get(url(alerts['51936282808'])).json()['expediente']['id']
    second = client.get(url(alerts['51999888777'])).json()['expediente']['id']
    assert first == second


def test_each_ong_gets_its_own_expediente(client, post_detection, payload, ong, river, sent):
    other = Ong.objects.create(name='Otra ONG')
    other.rivers.add(river)
    Member.objects.create(ong=other, full_name='Ana Soto', phone='51911222333')
    post_detection(payload)
    ids = {client.get(url(a)).json()['expediente']['id'] for a in Alert.objects.all()}
    assert len(ids) == 2


def test_autosave_remembers_the_answers_for_next_time(client, maria):
    resp = patch(client, maria, {'rep_dni': '12345678', 'ong_address': 'Jr. Próspero 123, Iquitos'})
    assert resp.status_code == 200
    assert Member.objects.get(pk=maria.member_id).dni == '12345678'
    assert Ong.objects.get(pk=maria.member.ong_id).address == 'Jr. Próspero 123, Iquitos'


def test_invalid_dni(client, maria):
    resp = patch(client, maria, {'rep_dni': '123'})
    assert resp.status_code == 400
    assert 'rep_dni' in resp.json()['field_errors']


def test_cannot_send_an_incomplete_expediente(client, maria, sent):
    resp = send(client, maria)
    assert resp.status_code == 400
    assert 'rep_dni' in resp.json()['field_errors']
    assert not any(template == 'condorin_codigo' for _, template, _ in sent)


def test_whatsapp_code_confirms_and_emails_the_final_pdf(client, maria, sent, fixed_code):
    patch(client, maria, COMPLETE)

    resp = send(client, maria)
    assert resp.status_code == 202
    assert resp.json()['phone_hint'] == '+51 *** *** 808'
    assert sent[-1][:2] == ('51936282808', 'condorin_codigo')

    wrong = send(client, maria, {'code': '000000'})
    assert wrong.status_code == 400 and wrong.json()['type'] == 'code_invalid'

    ok = send(client, maria, {'code': fixed_code})
    assert ok.status_code == 200
    exp = ok.json()['expediente']
    assert exp['status'] == 'ready' and exp['folio'].startswith('CND-2026-')
    assert ok.json()['sent']['emailed_to'] == ['denuncias@amazoniaviva.org', 'maria@example.org']
    assert mail.outbox[0].attachments[0][0] == f"{exp['folio']}.pdf"

    pdf = client.get(url(maria) + '?formato=pdf')
    assert pdf['Content-Type'] == 'application/pdf'
    assert pdf.content.startswith(b'%PDF')


def test_final_pdf_is_archived_in_the_bucket(client, maria, fixed_code, settings, monkeypatch):
    from core import gcs
    settings.GCS_EXPEDIENTES_BUCKET = 'condorin-expedientes'
    uploads = []

    def fake_upload(bucket, name, content, content_type):
        uploads.append((bucket, name, content, content_type))
        return '42'

    monkeypatch.setattr(gcs, 'upload', fake_upload)
    exp = finalize(client, maria, fixed_code).json()['expediente']
    bucket, name, content, content_type = uploads[0]
    assert name.startswith(f"expedientes/2026/{exp['folio']}-") and content.startswith(b'%PDF')
    assert exp['pdf_gcs_uri'] == f'gs://{bucket}/{name}#42'


def test_final_pdf_still_works_when_the_bucket_fails(client, maria, fixed_code, settings):
    settings.GCS_EXPEDIENTES_BUCKET = 'condorin-expedientes'  # GCS is unreachable in tests
    resp = finalize(client, maria, fixed_code)
    assert resp.status_code == 200 and resp.json()['expediente']['pdf_gcs_uri'] == ''


def test_code_from_one_member_does_not_work_for_another(client, alerts, fixed_code):
    maria, jose = alerts['51936282808'], alerts['51999888777']
    patch(client, maria, COMPLETE)
    send(client, maria)
    assert send(client, jose, {'code': fixed_code}).json()['type'] == 'code_expired'


def test_too_many_wrong_codes(client, maria, fixed_code):
    patch(client, maria, COMPLETE)
    send(client, maria)
    for _ in range(codes.MAX_ATTEMPTS):
        send(client, maria, {'code': '000000'})
    assert send(client, maria, {'code': fixed_code}).json()['type'] == 'code_expired'


def test_draft_pdf_preview(client, maria):
    resp = client.get(url(maria) + '?formato=pdf')
    assert resp.status_code == 200
    assert resp.content.startswith(b'%PDF')
    assert 'borrador' in resp['Content-Disposition']


def test_filing_receipt_locks_the_expediente(client, maria, fixed_code):
    patch(client, maria, COMPLETE)
    early = patch(client, maria, {'filings': [{'authority': 'fema', 'receipt_number': 'X', 'filed_at': '2026-10-18'}]})
    assert early.status_code == 400

    finalize(client, maria, fixed_code)
    resp = patch(client, maria, {'filings': [
        {'authority': 'fema', 'receipt_number': 'MP-2026-000123', 'filed_at': '2026-10-18'},
    ]})
    assert resp.json()['expediente']['status'] == 'filed'
    fema = next(a for a in resp.json()['authorities'] if a['code'] == 'fema')
    assert fema['filing']['receipt_number'] == 'MP-2026-000123'

    assert patch(client, maria, {'facts': 'otra cosa'}).status_code == 409
    assert Expediente.objects.get().facts != 'otra cosa'


def test_ready_expediente_can_be_reopened_to_fix_it(client, maria, fixed_code):
    finalize(client, maria, fixed_code)

    assert patch(client, maria, {'rep_position': 'Directora'}).status_code == 409
    resp = patch(client, maria, {'reopen': True, 'rep_position': 'Directora'})
    assert resp.status_code == 200
    assert resp.json()['expediente']['status'] == 'draft'


def test_event_page_does_not_open_the_expediente(client, maria):
    data = client.get(f'/api/v1/eventos/{maria.token}').json()
    assert data['incident']['river']['name'] == 'Yaguas' and data['incident']['detections'][0]['maps_url']
    assert data['ong']['name'] == 'Amazonía Viva'
    # Only the automatic draft from ingest exists, and reading the event page leaves it untouched.
    assert data['expediente']['status_label'] == 'Borrador listo para revisar'
    assert Expediente.objects.get().updated_by is None
    assert Alert.objects.get(pk=maria.pk).opened_at is None

    client.get(url(maria))
    assert client.get(f'/api/v1/eventos/{maria.token}').json()['expediente']['status'] == 'draft'


def test_event_page_unknown_token(client, db):
    assert client.get('/api/v1/eventos/nope').status_code == 404
