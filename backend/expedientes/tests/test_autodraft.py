"""Automatic drafts: one per scene and watching ONG, created at ingest, silent, and found by the link."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from detections.models import Alert, SatelliteImage
from expedientes.models import Expediente
from ongs.models import Member, Ong
from ongs.team import internal_team
from panel.views import panel_payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def others(river):
    """An inactive ONG and the internal team on the same river: neither gets a draft."""
    inactive = Ong.objects.create(name='ONG Dormida', active=False)
    inactive.rivers.add(river)
    internal_team().rivers.add(river)
    return inactive


def test_ingest_drafts_only_for_watching_active_ongs(post_detection, payload, ong, others, sent):
    assert post_detection(payload).status_code == 201

    expediente = Expediente.objects.get()
    assert expediente.ong == ong and expediente.auto_created
    assert expediente.created_by is None and expediente.updated_by is None
    assert expediente.status == Expediente.Status.DRAFT
    assert 'Yaguas' in expediente.place_reference and expediente.facts
    assert 'google.com/maps' in expediente.field_evidence_links
    assert expediente.authorities.exists()
    assert expediente.ong_name == ong.name


def test_reingest_is_idempotent(post_detection, payload, ong, sent):
    post_detection(payload)
    post_detection(payload)
    image = SatelliteImage.objects.get()
    from expedientes.autodraft import create_drafts
    assert create_drafts(image) == []
    assert Expediente.objects.count() == 1


def test_old_scene_gets_a_draft_but_no_alert(settings, post_detection, payload, ong, sent):
    settings.ALERT_RECENT_DAYS = 7
    payload['image']['captured_at'] = (timezone.now() - timedelta(days=30)).isoformat()
    resp = post_detection(payload)

    assert resp.json()['reason'] == 'old_scene'
    assert sent == [] and not Alert.objects.exists() and mail.outbox == []
    assert Expediente.objects.filter(ong=ong, auto_created=True).count() == 1


def test_legal_representative_signs_the_draft(post_detection, payload, ong, sent):
    Member.objects.create(ong=ong, full_name='Rosa Tapullima', phone='51911111111', dni='12345678',
                          position='Presidenta', is_legal_representative=True, email='rosa@example.org')
    post_detection(payload)
    expediente = Expediente.objects.get()
    assert (expediente.rep_name, expediente.rep_dni, expediente.notify_email) == (
        'Rosa Tapullima', '12345678', 'rosa@example.org')


def test_link_finds_the_draft_and_panel_shows_it_ready_to_review(client, post_detection, payload, ong, sent):
    post_detection(payload)
    draft = Expediente.objects.get()
    member = ong.members.get(phone='51936282808')

    totals = panel_payload(member, False)['totals']
    assert totals['without_expediente'] == 0 and totals['draft'] == 1
    row = panel_payload(member, False)['incidents'][0]['expediente']
    assert row['status_label'] == 'Borrador listo para revisar' and row['missing'] >= 1

    alert = Alert.objects.get(member=member)
    resp = client.get(f'/api/v1/expedientes/{alert.token}')
    assert resp.status_code == 200
    draft.refresh_from_db()
    assert Expediente.objects.count() == 1
    assert draft.updated_by is None and draft.rep_name == 'María Huamán Ríos'


def test_mapa_activity_ignores_untouched_drafts(client, post_detection, payload, ong, sent):
    post_detection(payload)
    data = client.get('/api/v1/mapa').json()
    assert data['totals']['expedientes'] == 1
    assert not [e for e in data['activity'] if e['kind'] == 'expediente_opened']


def test_backfill_counts_then_creates(payload, ong, others, river, capsys):
    image = SatelliteImage.objects.create(
        idempotency_key='k1', river=river, bucket='b', object_name='o', generation='1', satellite='Sentinel-1',
        captured_at=timezone.now() - timedelta(days=90), model_name='m', model_version='v', payload={})
    image.detections.create(index=0, lat=-2.77, lon=-70.95, confidence=0.9, bbox=[0, 0, 1, 1])

    call_command('backfill_expedientes')
    assert '1 ' in capsys.readouterr().out and not Expediente.objects.exists()

    call_command('backfill_expedientes', '--yes')
    assert Expediente.objects.filter(image=image, ong=ong, auto_created=True).count() == 1
    call_command('backfill_expedientes', '--yes')
    assert Expediente.objects.count() == 1
