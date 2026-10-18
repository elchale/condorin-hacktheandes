"""GET /api/v1/fuentes: live open data for the map (contract D), public and cacheable.

The encoded body (plain and gzip, compressed once) lives in the process cache for
FUENTES_CACHE_SECONDS, so a burst of visitors costs one read of the cache table and one compression.
Browsers and CDNs keep it five minutes and may serve it stale for an hour; the ETag (which ignores
`generated_at`) turns a revalidation into a 304.

POST /api/v1/fuentes/refresh (Bearer PANEL_API_SECRET) refreshes the stale sources synchronously; the
refresh-feeds GitHub workflow calls it every 30 minutes.
"""
import gzip
import hashlib
import json
import threading

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.cache import get_conditional_response, patch_vary_headers
from rest_framework.response import Response
from rest_framework.views import APIView

from mapa.middleware import cors
from panel.auth import authenticate_frontend

from .services import get_payload, refresh_due

CACHE_KEY = 'fuentes:public:v1'
PUBLIC_CACHE = 'public, max-age=300, stale-while-revalidate=3600'

_build_lock = threading.Lock()


def encode(payload: dict) -> tuple[bytes, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    stable = json.dumps({**payload, 'generated_at': None}, sort_keys=True).encode()
    return body, gzip.compress(body, compresslevel=6), f'"{hashlib.sha256(stable).hexdigest()[:32]}"'


def public_body() -> tuple[bytes, bytes, str]:
    seconds = getattr(settings, 'FUENTES_CACHE_SECONDS', 60)
    if seconds <= 0:
        return encode(get_payload())
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    with _build_lock:
        cached = cache.get(CACHE_KEY)
        if cached is None:
            cached = encode(get_payload())
            cache.set(CACHE_KEY, cached, seconds)
    return cached


class FuentesView(APIView):
    throttle_scope = 'fuentes'

    def get(self, request):
        body, gz, etag = public_body()
        response = get_conditional_response(request, etag=etag)
        if response is None:
            if 'gzip' in request.META.get('HTTP_ACCEPT_ENCODING', ''):
                response = HttpResponse(gz, content_type='application/json; charset=utf-8')
                response['Content-Encoding'] = 'gzip'  # GZipMiddleware leaves it alone
            else:
                response = HttpResponse(body, content_type='application/json; charset=utf-8')
        response['ETag'] = etag
        response['Cache-Control'] = PUBLIC_CACHE
        patch_vary_headers(response, ['Accept-Encoding'])
        return cors(response)

    def finalize_response(self, request, response, *args, **kwargs):
        return cors(super().finalize_response(request, response, *args, **kwargs))


class FuentesRefreshView(APIView):
    """Refresh the stale feeds now (all with ?force=1) and report each source; 502 when all tried failed."""
    throttle_scope = 'panel'

    def post(self, request):
        authenticate_frontend(request)
        force = request.query_params.get('force') in ('1', 'true')
        result = refresh_due(force=force)
        cache.delete(CACHE_KEY)
        tried = [r for r in result.values() if r['status'] in ('ok', 'failed')]
        failed = tried and all(r['status'] == 'failed' for r in tried)
        return Response({'force': force, 'sources': result}, status=502 if failed else 200)
