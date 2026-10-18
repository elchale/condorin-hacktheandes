"""Core middleware.

Provides:
- RequestIdMiddleware  — reads (when well formed) or generates X-Request-Id, echoes it in the response
- AccessLogsMiddleware — one log line per request (method/path/status/ms/ip), with personal tokens redacted

It is the only access log: gunicorn runs without --access-logfile, which would print the raw paths.
"""
import logging
import re
import threading
import time
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)
access_logger = logging.getLogger('access')

# Thread-local storage for request_id so log filters can pick it up
_local = threading.local()

# A caller supplied id is echoed and logged only when it is short and plain; anything else gets a new one.
REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')

# Path segments that are bearer secrets: the personal alert token opens (and edits) an expediente.
TOKEN_PATH_RE = re.compile(r'(/api/v1/(?:expedientes|eventos)/)[^/\s?"]+')


def get_current_request_id() -> str:
    return getattr(_local, 'request_id', '')


def redact_path(path: str) -> str:
    """'/api/v1/expedientes/abc123/enviar' → '/api/v1/expedientes/<token>/enviar'"""
    return TOKEN_PATH_RE.sub(r'\1<token>', path)


def mask_phone(phone) -> str:
    """'51936282808' → '*******2808': enough to tell people apart in a log, not to message them."""
    text = str(phone or '')
    return '*' * max(len(text) - 4, 0) + text[-4:]


def client_ip(request) -> str:
    """The caller's address the way the throttles see it: with NUM_PROXIES proxies in front (Cloud Run: 1), the
    entry they appended to X-Forwarded-For, so a forged first entry is never logged as the client."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    proxies = settings.REST_FRAMEWORK.get('NUM_PROXIES')
    if forwarded and proxies:
        addresses = [a.strip() for a in forwarded.split(',')]
        return addresses[-min(proxies, len(addresses))]
    return request.META.get('REMOTE_ADDR', '')


class RedactTokensFilter(logging.Filter):
    """Redacts alert tokens from every log line (Django's own "Not Found: /api/v1/expedientes/..." included)."""

    def filter(self, record):
        message = record.getMessage()
        redacted = redact_path(message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


class RequestIdMiddleware:
    """Read or generate X-Request-Id header; echo it back in the response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.META.get('HTTP_X_REQUEST_ID', '')
        request_id = supplied if REQUEST_ID_RE.match(supplied) else str(uuid.uuid4())
        request.request_id = request_id
        _local.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            # Worker threads are reused: the next request on this thread must not inherit the id.
            _local.request_id = ''
        response['X-Request-Id'] = request_id
        return response


class AccessLogsMiddleware:
    """Log one line per request: method, path (tokens redacted), status, duration, user, ip."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        user = getattr(request, 'user', None)
        user_id = user.pk if user is not None and user.is_authenticated else None

        access_logger.info(
            '%s %s %s %sms ip=%s user=%s rid=%s',
            request.method, redact_path(request.path), response.status_code, duration_ms,
            client_ip(request), user_id, getattr(request, 'request_id', ''),
        )
        return response
