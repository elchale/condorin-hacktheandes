"""The demo clock: what day it is for the API, what it hides, and the alerts it sends when the day moves."""
import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core import clock
from detections.models import Alert, SatelliteImage

pytestmark = pytest.mark.django_db


def scene(post_detection, payload, captured_at: str, key: str):
    body = json.loads(json.dumps(payload))
    body['image']['captured_at'] = captured_at
    body['image']['object'] = f'yaguas/{captured_at[:10]}_s1.tif'
    resp = post_detection(body, key=key)
    assert resp.status_code == 201
    return SatelliteImage.objects.get(idempotency_key=key)


def test_real_time_by_default():
    assert not clock.is_simulated()
    assert abs((clock.now() - timezone.now()).total_seconds()) < 2
    p = clock.payload()
    assert set(p) == {'now', 'today', 'label', 'simulated', 'timezone'}
    assert p['simulated'] is False and p['timezone'] == 'America/Lima'
    assert p['today'] == timezone.localdate().isoformat()


def test_set_a_day_keeps_the_time_of_day_and_ticks():
    clock.set_demo('2026-07-10')
    local = timezone.localtime(clock.now())
    real = timezone.localtime()
    assert (local.year, local.month, local.day) == (2026, 7, 10)
    assert abs((local.replace(year=real.year, month=real.month, day=real.day) - real).total_seconds()) < 2
    assert clock.is_simulated() and clock.today().isoformat() == '2026-07-10'
    assert clock.payload()['label'] == 'viernes 10 de julio de 2026'

    clock.set_demo('2026-07-10T09:00')
    assert timezone.localtime(clock.now()).strftime('%Y-%m-%d %H:%M') == '2026-07-10 09:00'

    clock.set_demo(None)
    assert not clock.is_simulated()


def test_demo_clock_hides_later_scenes_from_map_and_panel(client, post_detection, payload, ong, sent, settings):
    settings.PANEL_API_SECRET = 'panel-secret'
    scene(post_detection, payload, '2026-07-10T10:42:00Z', 'k-jul-10')
    scene(post_detection, payload, '2026-07-20T10:42:00Z', 'k-jul-20')
    assert client.get('/api/v1/mapa').json()['totals']['images'] == 2

    clock.set_demo('2026-07-12T09:00')
    mapa = client.get('/api/v1/mapa').json()
    assert mapa['clock']['today'] == '2026-07-12' and mapa['clock']['simulated'] is True
    assert mapa['totals']['images'] == 1
    assert [i['captured_at'] for i in mapa['images']] == ['2026-07-10T10:42:00Z']
    assert all(ev['at'] <= '2026-07-12T14:00:00Z' for ev in mapa['activity'])
    assert mapa['generated_at'].startswith('2026-07-12T14:00')

    panel = client.get('/api/v1/panel', HTTP_AUTHORIZATION='Bearer panel-secret', HTTP_X_CONDORIN_PHONE='51936282808').json()
    assert panel['clock']['label'] == 'domingo 12 de julio de 2026'
    assert panel['totals']['incidents'] == 1

    clock.set_demo(None)
    assert client.get('/api/v1/mapa').json()['totals']['images'] == 2


def test_set_today_sends_that_days_alerts_once(post_detection, payload, ong, sent, settings):
    settings.ALERT_RECENT_DAYS = 7
    # Both scenes are old for the real clock, so nobody is alerted when they arrive.
    jul10 = scene(post_detection, payload, '2026-07-10T10:42:00Z', 'k-jul-10')
    scene(post_detection, payload, '2026-07-11T10:42:00Z', 'k-jul-11')
    assert not Alert.objects.exists() and not sent

    out = StringIO()
    call_command('set_today', '2026-07-10T09:00', stdout=out)
    # 09:00 Lima is before the 05:42 Lima capture? No: 10:42Z is 05:42 Lima, so the scene already exists.
    assert Alert.objects.filter(image=jul10, status=Alert.Status.SENT).count() == 2
    assert Alert.objects.count() == 2  # the 11 July scene is still in the future
    assert len(sent) == 2
    for alert in Alert.objects.all():
        assert timezone.localtime(alert.sent_at).strftime('%Y-%m-%d') == '2026-07-10'
    assert 'Scene' in out.getvalue() and '2 queued, 2 sent' in out.getvalue()

    # Again the same day: nothing new goes out.
    call_command('set_today', '2026-07-10T12:00', stdout=StringIO())
    assert len(sent) == 2

    # The next day: only that day's scene alerts.
    call_command('set_today', '2026-07-11', stdout=StringIO())
    assert Alert.objects.count() == 4 and len(sent) == 4

    out = StringIO()
    call_command('set_today', '--real', stdout=out)
    assert 'real' in out.getvalue() and not clock.is_simulated()


def test_set_today_sends_every_scene_still_recent(post_detection, payload, ong, sent, settings):
    settings.ALERT_RECENT_DAYS = 7
    old = scene(post_detection, payload, '2026-07-01T10:42:00Z', 'k-jul-01')
    jul05 = scene(post_detection, payload, '2026-07-05T10:42:00Z', 'k-jul-05')
    jul08 = scene(post_detection, payload, '2026-07-08T10:42:00Z', 'k-jul-08')
    later = scene(post_detection, payload, '2026-07-12T10:42:00Z', 'k-jul-12')
    assert not sent

    out = StringIO()
    call_command('set_today', '2026-07-10T09:00', stdout=out)
    # 5 and 8 July are within the week before 10 July; 1 July is too old and 12 July has not happened yet.
    assert set(Alert.objects.values_list('image', flat=True)) == {jul05.pk, jul08.pk}
    assert len(sent) == 4 and out.getvalue().count('Scene') == 2
    assert not Alert.objects.filter(image__in=[old, later]).exists()

    # Jumping ahead sends only what is new in the window.
    call_command('set_today', '2026-07-12T09:00', stdout=StringIO())
    assert len(sent) == 6 and Alert.objects.filter(image=later).count() == 2


def test_set_today_without_time_before_the_capture_waits(post_detection, payload, ong, sent, settings):
    settings.ALERT_RECENT_DAYS = 7
    scene(post_detection, payload, '2026-07-10T23:30:00Z', 'k-late')  # 18:30 Lima
    call_command('set_today', '2026-07-10T09:00', stdout=StringIO())
    assert not sent  # that scene has not been captured yet on the demo day
    call_command('set_today', '2026-07-10T19:00', stdout=StringIO())
    assert len(sent) == 2


def test_no_send_moves_the_clock_quietly(post_detection, payload, ong, sent, settings):
    settings.ALERT_RECENT_DAYS = 7
    scene(post_detection, payload, '2026-07-10T10:42:00Z', 'k-jul-10')
    out = StringIO()
    call_command('set_today', '2026-07-10T09:00', '--no-send', stdout=out)
    assert clock.today().isoformat() == '2026-07-10' and not sent and not Alert.objects.exists()
    call_command('set_today', '--resend', stdout=StringIO())
    assert len(sent) == 2


def test_alert_link_signs_in_under_the_demo_clock(client, post_detection, payload, ong, sent, settings):
    settings.ALERT_RECENT_DAYS = 7
    scene(post_detection, payload, '2026-07-10T10:42:00Z', 'k-jul-10')
    call_command('set_today', '2026-07-10T09:00', stdout=StringIO())
    alert = Alert.objects.get(member__phone='51936282808')
    assert alert.sent_at and alert.sent_at <= clock.now()
    resp = client.post('/api/v1/auth/enlace', json.dumps({'token': alert.token}), content_type='application/json')
    assert resp.status_code == 200 and resp.json()['via'] == 'link'


def test_status_without_arguments(capsys):
    out = StringIO()
    call_command('set_today', stdout=out)
    assert 'today is' in out.getvalue() and 'real' in out.getvalue()


def test_unreadable_clock_falls_back_to_real_time(monkeypatch):
    from django.db import DatabaseError

    from core.models import Clock

    def boom(*args, **kwargs):
        raise DatabaseError('down')

    monkeypatch.setattr(Clock.objects, 'filter', boom)
    assert abs((clock.now() - timezone.now()).total_seconds() + 0) < 2


def test_day_bounds_are_lima_days():
    start, end = clock.day_bounds(clock.parse('2026-07-10').date())
    assert start.isoformat() == '2026-07-10T00:00:00-05:00'
    assert end - start == timedelta(days=1)
