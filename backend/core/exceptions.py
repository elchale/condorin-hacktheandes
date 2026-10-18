"""Core exception classes and DRF exception handler.

The envelope format is:
    {"message": "...", "type": "<snake_case_class>", "field_errors": {field: [msg]}}

Frontend switches on ``type`` to display domain-specific error UI.
"""
import logging
import re
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

CAMEL_TO_SNAKE_RE = re.compile('((?<=[a-z0-9])[A-Z]|(?!^)[A-Z](?=[a-z]))')


def camel_to_snake_string(value: str) -> str:
    return CAMEL_TO_SNAKE_RE.sub(r'_\1', value).lower()


class BaseError(exceptions.APIException):
    """Base system error. Must be subclassed — never raised directly."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __new__(cls, *args, **kwargs) -> Any:
        if cls is BaseError:
            raise RuntimeError('BaseError should not be instantiated directly.')

        cls.code = camel_to_snake_string(cls.__name__)
        instance = super().__new__(cls, *args, **kwargs)
        instance._args = args
        instance._kwargs = kwargs
        return instance

    def __init__(self, detail=None, code=None):
        # Prefer the class-derived snake_case name over APIException's generic
        # default_code of 'error'.  Callers can still pass an explicit code.
        resolved_type = code or self.code
        super().__init__(
            detail={
                'message': detail or self.default_detail,
                'type': resolved_type,
            },
            code=resolved_type,
        )


class UnknownError(BaseError):
    default_detail = _('Unknown error.')


def envelope_exception_handler(exc, context):
    """DRF exception handler that normalises all errors to the envelope shape.

    Maps:
    - ValidationError      → 400, field_errors populated
    - NotAuthenticated     → 401
    - PermissionDenied     → 403
    - NotFound             → 404
    - MethodNotAllowed     → 405
    - Throttled            → 429
    - BaseError subclasses → their own status_code
    - Unhandled Exception  → 500, logged
    """
    # Let DRF do its own processing first
    response = drf_exception_handler(exc, context)

    if response is None:
        # Unhandled server error
        logger.exception('Unhandled exception in view: %s', exc)
        return Response(
            {'message': 'Internal server error.', 'type': 'server_error', 'field_errors': {}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    message = ''
    error_type = 'error'
    field_errors: dict = {}

    if isinstance(exc, exceptions.ValidationError):
        error_type = 'validation_error'
        if isinstance(data, dict):
            # DRF puts non_field_errors under 'non_field_errors' key
            non_field = data.pop('non_field_errors', [])
            message = '; '.join(str(e) for e in non_field) if non_field else 'Validation error.'
            # Remaining keys are field-level errors
            for field, errs in data.items():
                if isinstance(errs, list):
                    field_errors[field] = [str(e) for e in errs]
                else:
                    field_errors[field] = [str(errs)]
        elif isinstance(data, list):
            message = '; '.join(str(e) for e in data)
        else:
            message = str(data)

    elif isinstance(exc, exceptions.NotAuthenticated):
        error_type = 'not_authenticated'
        message = str(data.get('detail', 'Authentication required.'))

    elif isinstance(exc, exceptions.PermissionDenied):
        error_type = 'permission_denied'
        message = str(data.get('detail', 'Permission denied.'))

    elif isinstance(exc, exceptions.NotFound):
        error_type = 'not_found'
        message = str(data.get('detail', 'Not found.'))

    elif isinstance(exc, exceptions.MethodNotAllowed):
        error_type = 'method_not_allowed'
        message = str(data.get('detail', 'Method not allowed.'))

    elif isinstance(exc, exceptions.Throttled):
        error_type = 'throttled'
        wait = exc.wait
        message = f'Request was throttled. Expected available in {int(wait)}s.' if wait else 'Request was throttled.'

    elif isinstance(exc, BaseError):
        # BaseError subclasses already carry message + type in their detail dict
        envelope = exc.detail if isinstance(exc.detail, dict) else {}
        message = str(envelope.get('message', str(exc.detail)))
        error_type = str(envelope.get('type', camel_to_snake_string(type(exc).__name__)))

    else:
        # Other DRF exceptions
        message = str(data.get('detail', str(data))) if isinstance(data, dict) else str(data)

    response.data = {
        'message': message,
        'type': error_type,
        'field_errors': field_errors,
    }
    return response
