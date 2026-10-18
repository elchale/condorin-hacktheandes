"""Who a webhook delivery alerts, and when: recent scenes only (today or yesterday in Lima), ONG members plus admins
with a phone, and never more than the hackathon cap of WhatsApp alerts."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import Admin
from core import clock
from detections import limits
from detections.models import Alert, SatelliteImage
from ongs.models import Ong, River

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def hackathon_window(settings, monkeypatch):
    """The live rule: today or yesterday in Lima (detections.limits), whatever ALERT_RECENT_DAYS says."""
    from detections import limits

    settings.ALERT_RECENT_DAYS = 7
    monkeypatch.setattr(limits, 'HACKATHON_ALERT_WINDOW_DAYS', 2)


@pytest.fixture
def admins(db):
    Admin.objects.create(email='carlos@example.org', name='Carlos', phone='51900000001')
    Admin.objects.create(email='nophone@example.org', name='Sin Teléfono')
    Admin.objects.create(email='gone@example.org', name='Inactivo', phone='51900000003', active=False)


def captured(days_ago: float) -> str:
    return (timezone.now() - timedelta(days=days_ago)).isoformat()


def test_recent_scene_alerts_members_and_admins(post_detection, payload, ong, admins, sent):
    payload['image']['captured_at'] = captured(1)
    resp = post_detection(payload)

    assert resp.status_code == 201
    assert resp.json()['alerted'] is True and resp.json()['reason'] == 'alerted'
    # Two ONG members and the one active admin with a phone; the admin without a phone is skipped.
    assert {phone for phone, _, _ in sent} == {'51936282808', '51999888777', '51900000001'}
    assert all(template == 'condorin_evento_v2' for _, template, _ in sent)
    admin_alert = Alert.objects.get(member__phone='51900000001')
    assert admin_alert.member.ong.internal and admin_alert.status == Alert.Status.SENT
    assert len({a.token for a in Alert.objects.all()}) == 3  # each recipient has a personal token


def test_old_scene_alerts_nobody(post_detection, payload, ong, admins, sent):
    payload['image']['captured_at'] = captured(30)
    resp = post_detection(payload)

    assert resp.status_code == 201
    assert resp.json()['alerted'] is False and resp.json()['reason'] == 'old_scene'
    assert SatelliteImage.objects.count() == 1  # still stored, still on the map
    assert not Alert.objects.exists() and not sent


def test_admin_without_phone_is_skipped(post_detection, payload, sent):
    Admin.objects.create(email='nophone@example.org', name='Sin Teléfono')
    payload['image']['captured_at'] = captured(0)
    resp = post_detection(payload)

    assert resp.json()['reason'] == 'no_recipients'
    assert not sent


def test_admin_in_a_watching_ong_gets_one_message(post_detection, payload, ong, sent):
    Admin.objects.create(email='maria@example.org', name='María', phone='51936282808')
    payload['image']['captured_at'] = captured(0)
    post_detection(payload)

    assert sorted(phone for phone, _, _ in sent) == ['51936282808', '51999888777']


def test_simulated_payload_alerts_nobody(post_detection, payload, ong, sent):
    payload['image']['captured_at'] = captured(0)
    payload['simulated'] = True
    assert post_detection(payload).json()['reason'] == 'simulated'
    assert not sent


def test_retry_picks_up_a_failed_alert(post_detection, payload, ong, admins, sent, monkeypatch):
    from core import whatsapp

    payload['image']['captured_at'] = captured(0)

    def down(phone, name, components):
        raise whatsapp.WhatsAppError('Meta is down')

    real = whatsapp.send_template
    monkeypatch.setattr(whatsapp, 'send_template', down)
    post_detection(payload)
    assert Alert.objects.filter(status=Alert.Status.FAILED).count() == 3

    monkeypatch.setattr(whatsapp, 'send_template', real)
    call_command('send_pending_alerts')
    assert Alert.objects.filter(status=Alert.Status.SENT).count() == 3
    assert len(sent) == 3


def test_new_river_is_watched_by_the_internal_team(post_detection, payload, admins, sent):
    payload['image']['captured_at'] = captured(0)
    post_detection(payload)  # creates the internal team
    team = Ong.objects.get(internal=True)

    river = River.objects.create(slug='nanay', name='Nanay')
    assert team.rivers.filter(pk=river.pk).exists()


def test_new_member_gets_no_old_alert(client, payload, ong, sent, settings, post_detection):
    from panel.services import member_for_phone

    payload['image']['captured_at'] = captured(30)
    post_detection(payload)
    member, joined = member_for_phone('51955555555')
    assert joined and not member.alerts.exists() and not sent


def lima_day(days_ago: int, hour: int = 12) -> str:
    """Noon (Lima) of a calendar day counted back from today in Lima."""
    from datetime import datetime, time
    tz = timezone.get_current_timezone()
    day = timezone.localtime(clock.now(), tz).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour), tzinfo=tz).isoformat()


def test_scene_from_yesterday_alerts(post_detection, payload, ong, sent):
    payload['image']['captured_at'] = lima_day(1, hour=0)  # the very start of yesterday in Lima
    assert post_detection(payload).json()['reason'] == 'alerted'
    assert len(sent) == 2


def test_scene_from_three_days_ago_does_not_alert(post_detection, payload, ong, sent):
    payload['image']['captured_at'] = lima_day(3)  # inside ALERT_RECENT_DAYS = 7, outside the hackathon window
    assert post_detection(payload).json()['reason'] == 'old_scene'
    assert not sent and not Alert.objects.exists()


def test_window_constant_overrides_the_setting(settings):
    settings.ALERT_RECENT_DAYS = 365
    start = timezone.localtime(limits.window_start(clock.now()))
    assert start.date() == timezone.localtime(clock.now()).date() - timedelta(days=1)
    assert (start.hour, start.minute) == (0, 0)


def fill_sent(n: int, river) -> None:
    """n alerts already sent, on some other scene, to n different members."""
    from ongs.models import Member, Ong

    other = SatelliteImage.objects.create(
        idempotency_key='earlier', river=river, bucket='b', object_name='o', generation='1', satellite='S1',
        captured_at=timezone.now(), model_name='m', model_version='v', payload={})
    filler = Ong.objects.create(name='Relleno', short_name='Relleno', ruc='20999999999')
    for i in range(n):
        member = Member.objects.create(ong=filler, full_name=f'M{i}', phone=f'5190100{i:04d}')
        Alert.objects.create(image=other, member=member, status=Alert.Status.SENT, sent_at=timezone.now())


def test_cap_lets_the_50th_out_and_caps_the_51st(post_detection, payload, ong, sent, river):
    fill_sent(limits.HACKATHON_MAX_ALERT_MESSAGES - 1, river)
    payload['image']['captured_at'] = lima_day(0, hour=0)
    resp = post_detection(payload)

    assert resp.json()['reason'] == 'alerted'
    assert len(sent) == 1  # two members, only one slot left
    statuses = sorted(Alert.objects.filter(image_id=resp.json()['id']).values_list('status', flat=True))
    assert statuses == [Alert.Status.CAPPED, Alert.Status.SENT]
    capped = Alert.objects.get(status=Alert.Status.CAPPED)
    assert capped.error == 'Límite de 50 mensajes del hackathon alcanzado' and capped.attempts == 0
    assert Alert.objects.filter(status=Alert.Status.SENT).count() == limits.HACKATHON_MAX_ALERT_MESSAGES


def test_capped_alerts_are_never_retried(post_detection, payload, ong, sent, river):
    fill_sent(limits.HACKATHON_MAX_ALERT_MESSAGES, river)
    payload['image']['captured_at'] = lima_day(0, hour=0)
    post_detection(payload)
    assert not sent and Alert.objects.filter(status=Alert.Status.CAPPED).count() == 2

    # Even once slots free up, a capped alert stays unsent: the retry only picks pending or failed.
    Alert.objects.filter(member__ong__name='Relleno').delete()
    call_command('send_pending_alerts', stdout=StringIO())
    assert not sent and Alert.objects.filter(status=Alert.Status.CAPPED).count() == 2


def test_webhook_reports_capped(post_detection, payload, ong, sent, river):
    fill_sent(limits.HACKATHON_MAX_ALERT_MESSAGES, river)
    payload['image']['captured_at'] = lima_day(0, hour=0)
    body = post_detection(payload).json()
    assert body['reason'] == 'capped' and body['alerted'] is False and not sent


def test_cap_stops_the_welcome_too(settings, sent, river):
    from panel.welcome import send_welcome

    settings.ALERTS_INLINE = True
    fill_sent(limits.HACKATHON_MAX_ALERT_MESSAGES, river)
    send_welcome('51955555555')
    assert not sent


def test_alerts_sent_before_the_cap_reset_do_not_count(river):
    fill_sent(limits.HACKATHON_MAX_ALERT_MESSAGES, river)
    assert limits.cap_reached()
    Alert.objects.update(sent_at=limits.HACKATHON_CAP_SINCE - timedelta(minutes=1))
    assert limits.sent_count() == 0 and not limits.cap_reached()
