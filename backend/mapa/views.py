"""GET /api/v1/mapa: the public map payload (contract A).

Public and cacheable: any origin may read it (Access-Control-Allow-Origin: *), browsers and CDNs keep it
60 s and may serve it stale for 10 min while revalidating, and the ETag turns a revalidation into a 304.
The anonymous payload is also kept in the process cache for MAPA_CACHE_SECONDS, so a burst of visitors
costs one set of queries. With a valid `Authorization: Bearer <session>` the response adds `mine` and
becomes private (never stored by a shared cache).
"""
import hashlib
import json
import threading

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.utils.cache import get_conditional_response, patch_vary_headers
from rest_framework.views import APIView

from accounts.session import bearer_phone
from core import clock
from ongs.models import Member

from .builder import build_mapa
from .middleware import cors

CACHE_KEY = 'mapa:public:v1'
PUBLIC_CACHE = 'public, max-age=60, stale-while-revalidate=600'
PRIVATE_CACHE = 'private, no-cache'

# One build per process at a time: when the cache expires, the other threads wait for it instead of
# all querying the database at once.
_build_lock = threading.Lock()


def _encode(payload: dict) -> tuple[bytes, str]:
    """The JSON body and its ETag. The ETag ignores the ticking clock, so it only changes with the data or the day."""
    body = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(',', ':')).encode()
    stable = json.dumps({**payload, 'generated_at': None, 'clock': payload.get('clock', {}).get('today')},
                        cls=DjangoJSONEncoder, sort_keys=True).encode()
    return body, f'"{hashlib.sha256(stable).hexdigest()[:32]}"'


def public_payload() -> tuple[bytes, str]:
    if settings.MAPA_CACHE_SECONDS <= 0:
        return _encode(build_mapa())
    key = f'{CACHE_KEY}:{clock.today()}'  # a change of day (demo clock) is a different payload
    cached = cache.get(key)
    if cached is not None:
        return cached
    with _build_lock:
        cached = cache.get(key)
        if cached is None:
            cached = _encode(build_mapa())
            cache.set(key, cached, settings.MAPA_CACHE_SECONDS)
    return cached


class MapaView(APIView):
    throttle_scope = 'mapa'

    def get(self, request):
        phone = bearer_phone(request)
        if phone is None:
            (body, etag), cache_control = public_payload(), PUBLIC_CACHE
        else:
            member = (Member.objects.select_related('ong')
                      .filter(phone=phone, active=True, ong__active=True, ong__internal=False)
                      .order_by('pk').first())
            (body, etag), cache_control = _encode(build_mapa(member=member, phone=phone)), PRIVATE_CACHE

        response = get_conditional_response(request, etag=etag) or HttpResponse(
            body, content_type='application/json; charset=utf-8')
        response['ETag'] = etag
        response['Cache-Control'] = cache_control
        patch_vary_headers(response, ['Authorization'])
        return cors(response)

    def finalize_response(self, request, response, *args, **kwargs):
        # Errors (a throttle 429) also carry the CORS header, so the browser can read them.
        return cors(super().finalize_response(request, response, *args, **kwargs))
