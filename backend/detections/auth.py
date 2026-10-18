"""Who may post detections: a Google ID token from an allowed service account, or the shared secret."""
import hmac
import logging

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from core.auth import bearer_token

logger = logging.getLogger(__name__)


def _bearer(request) -> str:
    token = bearer_token(request)
    if token is None:
        raise NotAuthenticated('Falta el encabezado Authorization: Bearer.')
    return token


def _valid_secret(token: str) -> bool:
    secret = settings.DETECTIONS_SHARED_SECRET
    return bool(secret) and hmac.compare_digest(token.encode(), secret.encode())


def _valid_id_token(token: str) -> bool:
    allowed = {email.lower() for email in settings.DETECTIONS_ALLOWED_SERVICE_ACCOUNTS}
    if not allowed or token.count('.') != 2:
        return False
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=settings.DETECTIONS_OIDC_AUDIENCE,
        )
    except Exception as exc:
        logger.warning('detections: rejected ID token: %s', exc)
        return False
    return bool(claims.get('email_verified')) and claims.get('email', '').lower() in allowed


def authenticate_detector(request) -> None:
    token = _bearer(request)
    if not (_valid_secret(token) or _valid_id_token(token)):
        raise AuthenticationFailed('Credencial inválida.')
