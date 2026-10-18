"""Core middleware.

Provides:
- RequestIdMiddleware  — reads/generates X-Request-Id, echoes in response
- AccessLogsMiddleware — structured per-request log (method/path/status/ms/user)
"""
import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)
access_logger = logging.getLogger('access')

# Thread-local storage for request_id so log filters can pick it up
_local = threading.local()


def get_current_request_id() -> str:
    return getattr(_local, 'request_id', '')


class RequestIdMiddleware:
    """Read or generate X-Request-Id header; echo it back in the response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get('HTTP_X_REQUEST_ID') or str(uuid.uuid4())
        request.request_id = request_id
        _local.request_id = request_id

        response = self.get_response(request)
        response['X-Request-Id'] = request_id
        return response


class AccessLogsMiddleware:
    """Log one line per request: method, path, status, duration, user, ip."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        user = getattr(request, 'user', None)
        user_id = user.pk if user is not None and user.is_authenticated else None

        ip = (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            or request.META.get('REMOTE_ADDR', '')
        )

        access_logger.info(
            '%s %s %s %sms ip=%s user=%s rid=%s',
            request.method, request.path, response.status_code, duration_ms,
            ip, user_id, getattr(request, 'request_id', ''),
        )
        return response
