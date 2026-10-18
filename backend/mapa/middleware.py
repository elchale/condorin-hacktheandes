"""Answers the CORS preflight of the public map for any origin.

django-cors-headers answers every preflight itself and only allows the configured origins, so this
runs before it for the one public route. GET responses get their headers from the view.
"""
from django.http import HttpResponse

PUBLIC_PATHS = frozenset({'/api/v1/mapa', '/api/v1/fuentes'})


def cors(response: HttpResponse) -> HttpResponse:
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response['Access-Control-Allow-Headers'] = 'Authorization, If-None-Match'
    response['Access-Control-Expose-Headers'] = 'ETag, X-Request-Id'
    response['Access-Control-Max-Age'] = '86400'
    return response


class PublicCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'OPTIONS' and request.path in PUBLIC_PATHS:
            return cors(HttpResponse(status=204))
        return self.get_response(request)
