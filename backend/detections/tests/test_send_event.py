"""manage.py send_event: a person sends one stored scene by hand."""
import pytest
from django.core.management import CommandError, call_command

from detections.models import Alert, SatelliteImage

pytestmark = pytest.mark.django_db


@pytest.fixture
def old_scene(post_detection, payload, ong, sent, settings):
    """A scene too old to alert on its own: stored, nobody messaged."""
    settings.ALERT_RECENT_DAYS = 7
    payload['image']['captured_at'] = '2025-07-10T10:00:00Z'
    post_detection(payload)
    assert sent == [] and not Alert.objects.exists()
    return SatelliteImage.objects.get()


def test_dry_run_sends_and_creates_nothing(old_scene, sent):
    call_command('send_event', old_scene.pk)
    assert sent == [] and not Alert.objects.exists()


def test_send_to_every_recipient_even_an_old_scene(old_scene, sent):
    call_command('send_event', old_scene.pk, '--send')
    assert {phone for phone, _, _ in sent} == {'51936282808', '51999888777'}
    assert set(Alert.objects.values_list('status', flat=True)) == {Alert.Status.SENT}

    # Already sent: skipped, unless --resend.
    call_command('send_event', old_scene.pk, '--send')
    assert len(sent) == 2
    call_command('send_event', old_scene.pk, '--send', '--resend', '--phone', '51936282808')
    assert len(sent) == 3 and sent[-1][0] == '51936282808'


def test_send_to_one_phone(old_scene, sent):
    call_command('send_event', old_scene.pk, '--send', '--phone', '51999888777')
    assert [phone for phone, _, _ in sent] == ['51999888777']


def test_unknown_phone_or_simulated_scene_is_refused(old_scene, sent):
    with pytest.raises(CommandError):
        call_command('send_event', old_scene.pk, '--send', '--phone', '51000000000')
    old_scene.payload = {**old_scene.payload, 'simulated': True}
    old_scene.save()
    with pytest.raises(CommandError):
        call_command('send_event', old_scene.pk, '--send')
    assert sent == []
