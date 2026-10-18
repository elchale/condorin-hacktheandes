"""Tests for envelope_exception_handler."""
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory

from core.exceptions import envelope_exception_handler


class DummyView:
    pass


def make_context():
    factory = APIRequestFactory()
    request = factory.get('/')
    return {'request': request, 'view': DummyView()}


class TestEnvelopeExceptionHandler:
    def test_validation_error_field_level(self):
        exc = ValidationError({'email': ['Enter a valid email address.']})
        response = envelope_exception_handler(exc, make_context())
        assert response.status_code == 400
        assert response.data['type'] == 'validation_error'
        assert 'email' in response.data['field_errors']

    def test_not_found(self):
        exc = NotFound('Resource not found.')
        response = envelope_exception_handler(exc, make_context())
        assert response.status_code == 404
        assert response.data['type'] == 'not_found'
        assert response.data['field_errors'] == {}

    def test_permission_denied(self):
        exc = PermissionDenied('Access denied.')
        response = envelope_exception_handler(exc, make_context())
        assert response.status_code == 403
        assert response.data['type'] == 'permission_denied'

    def test_validation_error_non_field(self):
        exc = ValidationError({'non_field_errors': ['Non-field error.']})
        response = envelope_exception_handler(exc, make_context())
        assert response.status_code == 400
        assert 'Non-field error.' in response.data['message']

    def test_base_error_subclass(self):
        from core.exceptions import UnknownError
        exc = UnknownError('Something went wrong')
        response = envelope_exception_handler(exc, make_context())
        assert response.status_code == 400
        assert response.data['type'] == 'unknown_error'
        assert 'field_errors' in response.data

    def test_unhandled_exception_returns_500(self):
        response = envelope_exception_handler(Exception('Boom'), make_context())
        assert response.status_code == 500
        assert response.data['type'] == 'server_error'
