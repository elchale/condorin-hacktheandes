"""Landing page and liveness probe."""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


@require_GET
def landing(request):
    return render(request, 'core/landing.html', {'frontend_url': settings.FRONTEND_URL})


@require_GET
@cache_control(no_cache=True, no_store=True)
def healthz(request):
    """Process liveness probe: 200 while the process is up."""
    return JsonResponse({'status': 'ok'})
