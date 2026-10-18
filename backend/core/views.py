"""Landing page, liveness probe (/healthz/) and readiness probe (/readyz/)."""
import logging

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def landing(request):
    return render(request, 'core/landing.html', {'frontend_url': settings.FRONTEND_URL})


@require_GET
@cache_control(no_cache=True, no_store=True)
def healthz(request):
    """Process liveness probe: 200 while the process is up."""
    return JsonResponse({'status': 'ok'})


@require_GET
@cache_control(no_cache=True, no_store=True)
def readyz(request):
    """Readiness: 200 when the database answers a SELECT 1, 503 when it does not. /healthz/ stays a pure
    liveness probe, so a Neon hiccup never makes Cloud Run restart a healthy process."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError as exc:
        logger.warning('readyz: database unreachable: %s', exc)
        return JsonResponse({'status': 'unavailable', 'database': 'down'}, status=503)
    return JsonResponse({'status': 'ok', 'database': 'ok'})
