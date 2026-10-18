"""Each alert is claimed (`sending`) before WhatsApp is called, so no two senders message the same member."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from detections import limits
from detections.models import Alert, SatelliteImage
from detections.services import process_image, send_alert

pytestmark = pytest.mark.django_db


@pytest.fixture
def queued(ong, river):
    """A stored scene with one pending alert per member, nothing sent yet."""
    image = SatelliteImage.objects.create(
        idempotency_key='k', river=river, bucket='b', object_name='o', generation='1', satellite='S1',
        captured_at=timezone.now(), model_name='m', model_version='v', payload={})
    image.detections.create(index=0, lat=-2.77, lon=-70.95, confidence=0.9, bbox=[1, 2, 3, 4])
    for member in ong.members.all():
        Alert.objects.create(image=image, member=member)
    return image


def test_a_stale_copy_of_a_sent_alert_is_not_sent_again(queued, sent):
    alert = Alert.objects.select_related('member').first()
    copy = Alert.objects.select_related('member').get(pk=alert.pk)  # what a second thread had loaded
    send_alert(alert)
    send_alert(copy)
    assert len(sent) == 1
    assert Alert.objects.get(pk=alert.pk).status == Alert.Status.SENT
    assert copy.status == Alert.Status.SENT and copy.attempts == 1  # refreshed from the row


def test_an_alert_being_sent_elsewhere_is_skipped(queued, sent):
    Alert.objects.filter(member__phone='51936282808').update(status=Alert.Status.SENDING, updated=timezone.now())
    process_image(queued.pk)
    assert [phone for phone, _, _ in sent] == ['51999888777']
    call_command('send_pending_alerts', stdout=StringIO())
    assert len(sent) == 1  # still claimed by the other sender


def test_an_abandoned_claim_is_retried(queued, sent, settings):
    settings.ALERT_SENDING_STALE_MINUTES = 10
    Alert.objects.update(status=Alert.Status.SENDING, updated=timezone.now() - timedelta(minutes=11))
    call_command('send_pending_alerts', stdout=StringIO())
    assert {phone for phone, _, _ in sent} == {'51936282808', '51999888777'}
    assert set(Alert.objects.values_list('status', flat=True)) == {Alert.Status.SENT}


def test_in_flight_alerts_take_a_slot_of_the_cap(queued, sent, monkeypatch):
    monkeypatch.setattr(limits, 'HACKATHON_MAX_ALERT_MESSAGES', 1)
    # Another instance claimed the last slot and is waiting for Meta: this one must not go out.
    Alert.objects.filter(member__phone='51936282808').update(status=Alert.Status.SENDING, updated=timezone.now())
    process_image(queued.pk)
    assert sent == []
    assert Alert.objects.get(member__phone='51999888777').status == Alert.Status.CAPPED


def test_failure_releases_the_claim(queued, monkeypatch):
    from core import whatsapp

    def down(*args):
        raise whatsapp.WhatsAppError('Meta down')

    monkeypatch.setattr(whatsapp, 'send_template', down)
    process_image(queued.pk)
    assert set(Alert.objects.values_list('status', flat=True)) == {Alert.Status.FAILED}
    assert set(Alert.objects.values_list('attempts', flat=True)) == {1}


def test_manual_resend_claims_a_sent_alert(queued, sent):
    alert = Alert.objects.select_related('member').first()
    send_alert(alert)
    send_alert(alert)  # automatic: already sent, skipped
    assert len(sent) == 1
    send_alert(alert, manual=True)  # manage.py send_event --resend
    assert len(sent) == 2 and Alert.objects.get(pk=alert.pk).attempts == 2
