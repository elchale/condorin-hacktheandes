"""Tests for RequestIdMiddleware."""
import pytest
from django.http import HttpResponse
from django.test import RequestFactory


@pytest.mark.django_db
class TestRequestIdMiddleware:
    def test_generates_request_id_if_absent(self, client):
        resp = client.get('/healthz/')
        assert 'X-Request-Id' in resp
        assert len(resp['X-Request-Id']) == 36  # UUID4 length

    def test_echoes_provided_request_id(self, client):
        resp = client.get('/healthz/', HTTP_X_REQUEST_ID='my-custom-id-123')
        assert resp['X-Request-Id'] == 'my-custom-id-123'

    def test_request_id_stored_on_request_object(self):
        from core.middleware import RequestIdMiddleware

        factory = RequestFactory()
        request = factory.get('/', HTTP_X_REQUEST_ID='test-id-456')
        response = HttpResponse()
        middleware = RequestIdMiddleware(lambda r: response)
        middleware(request)
        assert request.request_id == 'test-id-456'

    def test_generates_uuid_when_header_absent(self):
        from core.middleware import RequestIdMiddleware

        factory = RequestFactory()
        request = factory.get('/')
        response = HttpResponse()
        middleware = RequestIdMiddleware(lambda r: response)
        result = middleware(request)
        assert hasattr(request, 'request_id')
        assert len(request.request_id) == 36
        assert result['X-Request-Id'] == request.request_id


@pytest.mark.parametrize('supplied', ['x' * 65, 'bad id', 'id\nInjected: 1', '<script>', ''])
def test_malformed_request_id_is_replaced(client, db, supplied):
    resp = client.get('/healthz/', HTTP_X_REQUEST_ID=supplied)
    assert resp['X-Request-Id'] != supplied and len(resp['X-Request-Id']) == 36


def test_thread_local_is_cleared_after_the_response():
    from core.middleware import RequestIdMiddleware, get_current_request_id

    request = RequestFactory().get('/', HTTP_X_REQUEST_ID='abc')
    RequestIdMiddleware(lambda r: HttpResponse())(request)
    assert get_current_request_id() == ''


def test_access_log_redacts_tokens_and_uses_the_proxy_ip(client, db, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger='access'):
        client.get('/api/v1/expedientes/SECRETTOKEN123/enviar', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7')
        client.get('/api/v1/eventos/SECRETTOKEN456')
    text = ' '.join(r.getMessage() for r in caplog.records if r.name == 'access')
    assert 'SECRETTOKEN' not in text
    assert '/api/v1/expedientes/<token>/enviar' in text and '/api/v1/eventos/<token>' in text
    assert 'ip=203.0.113.7' in text and '6.6.6.6' not in text


def test_mask_phone():
    from core.middleware import mask_phone

    assert mask_phone('51936282808') == '*******2808'
    assert mask_phone('') == ''


def test_dry_run_never_logs_the_code(settings, caplog):
    import logging

    from core import whatsapp

    settings.WA_SEND_ENABLED = False
    with caplog.at_level(logging.INFO):
        whatsapp.send_code('51936282808', '482913')
    assert '482913' not in caplog.text and '51936282808' not in caplog.text and '2808' in caplog.text


def test_every_log_line_is_redacted_by_the_console_filter():
    import logging

    from core.middleware import RedactTokensFilter

    record = logging.LogRecord('django.request', logging.WARNING, '', 0, 'Not Found: %s', ('/api/v1/eventos/abc',), None)
    RedactTokensFilter().filter(record)
    assert record.getMessage() == 'Not Found: /api/v1/eventos/<token>'
