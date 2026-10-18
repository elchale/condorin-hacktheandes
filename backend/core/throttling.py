"""DRF throttles. The scopes that guard sign in codes count in the shared cache (the `django_cache` table), so
the limits hold across every Cloud Run instance; the high volume scopes count in process memory."""
from django.core.cache import caches
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

# Counted in the shared DatabaseCache: brute force or WhatsApp spam would otherwise get one budget per instance.
SHARED_SCOPES = {'auth_code', 'auth_enter', 'expediente_send', 'panel_link'}  # PhoneThrottle is always shared


class ScopedThrottle(ScopedRateThrottle):
    """ScopedRateThrottle whose counters live in the shared cache for SHARED_SCOPES, in `local` otherwise."""

    def allow_request(self, request, view):
        scope = getattr(view, self.scope_attr, None)
        self.cache = caches['default' if scope in SHARED_SCOPES else 'local']
        return super().allow_request(request, view)


class PhoneThrottle(SimpleRateThrottle):
    """A second budget keyed on the normalized phone, whatever the IP: stops a botnet from flooding one number
    with WhatsApp codes or spreading guesses for it over many addresses.

    The view names the rate with `phone_throttle_scope` and says which phone a request is for with
    `throttle_phone(request)` (None: not counted). Counted in the shared cache.
    """
    scope_attr = 'phone_throttle_scope'

    def __init__(self):
        pass  # the rate depends on the view, set in allow_request (like ScopedRateThrottle)

    def allow_request(self, request, view):
        self.scope = getattr(view, self.scope_attr, None)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        self.cache = caches['default']
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        phone = view.throttle_phone(request)
        if not phone:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': phone}
