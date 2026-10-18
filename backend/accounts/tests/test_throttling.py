"""Throttles count the real client behind Cloud Run (NUM_PROXIES) and each phone on its own budget."""
import json

import pytest
from django.core.cache import cache

from core.throttling import PhoneThrottle, ScopedThrottle

pytestmark = pytest.mark.django_db

CLIENT_IP = '203.0.113.7'


@pytest.fixture(autouse=True)
def _demo(settings):
    settings.DEFAULT_ONG_ID = 0


@pytest.fixture
def rates(monkeypatch):
    """Small budgets. DRF reads the rates once at import, so the class attribute is what counts."""
    def use(**scopes):
        monkeypatch.setattr(ScopedThrottle, 'THROTTLE_RATES', {**ScopedThrottle.THROTTLE_RATES, **scopes})
        monkeypatch.setattr(PhoneThrottle, 'THROTTLE_RATES', {**PhoneThrottle.THROTTLE_RATES, **scopes})
    return use


def ask_code(client, phone, forwarded_for):
    return client.post('/api/v1/auth/codigo', json.dumps({'phone': phone, 'consent': True}),
                       content_type='application/json', HTTP_X_FORWARDED_FOR=forwarded_for)


def test_one_proxy_by_default(settings):
    assert settings.REST_FRAMEWORK['NUM_PROXIES'] == 1


def test_a_spoofed_forwarded_for_does_not_buy_a_new_budget(client, ong, sent, rates):
    rates(auth_code='3/hour')
    # The caller writes whatever it likes first; Cloud Run appends the address it really saw last.
    for i in range(3):
        assert ask_code(client, f'91122233{i}', f'10.0.0.{i}, {CLIENT_IP}').status_code == 202
    blocked = ask_code(client, '911222339', f'10.9.9.9, {CLIENT_IP}')
    assert blocked.status_code == 429 and blocked.json()['type'] == 'throttled'
    # Another real client still has its own budget.
    assert ask_code(client, '911222338', '10.0.0.1, 198.51.100.4').status_code == 202


def test_one_phone_has_its_own_budget_across_ips(client, ong, sent, rates):
    rates(auth_code_phone='2/hour')
    for i in range(2):
        assert ask_code(client, '936282808', f'198.51.100.{i}').status_code == 202
        cache.delete('otp-sent:51936282808')  # past the 45 s resend lock
    blocked = ask_code(client, '936 282 808', '198.51.100.99')  # same number, written another way
    assert blocked.status_code == 429 and blocked.json()['type'] == 'throttled'
    assert ask_code(client, '911222333', '198.51.100.99').status_code == 202  # other phones are not affected


def test_guesses_for_one_phone_are_counted_across_ips(client, ong, sent, rates):
    rates(auth_enter_phone='2/hour')
    pending = ask_code(client, '936282808', CLIENT_IP).json()['pending']

    def enter(ip):
        return client.post('/api/v1/auth/entrar', json.dumps({'pending': pending, 'code': '000000'}),
                           content_type='application/json', HTTP_X_FORWARDED_FOR=ip)

    assert enter('198.51.100.1').status_code == 400
    assert enter('198.51.100.2').status_code == 400
    assert enter('198.51.100.3').status_code == 429


def test_a_forged_pending_value_only_spends_the_ip_budget(client, ong, rates):
    rates(auth_enter_phone='1/hour')
    for _ in range(3):
        resp = client.post('/api/v1/auth/entrar', json.dumps({'pending': 'forged', 'code': '123456'}),
                           content_type='application/json')
        assert resp.json()['type'] == 'code_expired'
