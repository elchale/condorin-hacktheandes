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
