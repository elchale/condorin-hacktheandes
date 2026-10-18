def test_landing_shows_the_condorin_logo(client):
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'brand/logo.png' in html
    assert 'Ojo de Cóndor' in html


def test_healthz(client):
    resp = client.get('/healthz/')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}


def test_readyz_checks_the_database(client, db):
    resp = client.get('/readyz/')
    assert resp.status_code == 200 and resp.json() == {'status': 'ok', 'database': 'ok'}


def test_readyz_reports_a_dead_database(client, db, monkeypatch):
    from django.db import DatabaseError

    from core import views

    class DeadConnection:
        def cursor(self):
            raise DatabaseError('server closed the connection')

    monkeypatch.setattr(views, 'connection', DeadConnection())
    resp = client.get('/readyz/')
    assert resp.status_code == 503 and resp.json()['database'] == 'down'


def test_test_settings_refuse_neon(monkeypatch):
    import importlib
    import sys

    import pytest

    from backend.settings import common

    monkeypatch.setitem(common.DATABASES['default'], 'HOST', 'ep-cool-1234-pooler.us-east-2.aws.neon.tech')
    monkeypatch.delitem(sys.modules, 'backend.test_settings')
    with pytest.raises(RuntimeError, match='Neon'):
        importlib.import_module('backend.test_settings')


def test_admin_stays_at_admin_by_default(client, settings):
    from django.urls import resolve

    assert settings.ADMIN_URL == 'admin/'
    assert resolve('/admin/').app_name == 'admin'


def test_admin_url_override(monkeypatch):
    import importlib

    from backend.settings import common

    monkeypatch.setenv('ADMIN_URL', '/gestion-interna/')
    try:
        assert importlib.reload(common).ADMIN_URL == 'gestion-interna/'
    finally:
        monkeypatch.delenv('ADMIN_URL')
        importlib.reload(common)
