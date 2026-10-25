"""External services: the detector webhook, WhatsApp Cloud API, Google Cloud Storage and email.

WhatsApp alerts go out on a background thread right after
the webhook commits, and `manage.py send_pending_alerts` retries whatever failed.
"""
from .env import env

# Detector webhook (POST /api/v1/detections). Either credential is accepted:
# a Google ID token minted for DETECTIONS_OIDC_AUDIENCE by one of the allowed service accounts,
# or the shared secret. Leave a side empty to turn it off.
DETECTIONS_SHARED_SECRET = env('DETECTIONS_SHARED_SECRET', default='')
DETECTIONS_OIDC_AUDIENCE = env('DETECTIONS_OIDC_AUDIENCE', default='https://api.condorin.pe/api/v1/detections')
DETECTIONS_ALLOWED_SERVICE_ACCOUNTS = env.list('DETECTIONS_ALLOWED_SERVICE_ACCOUNTS', default=[])
# Detections below this confidence are stored but do not alert anyone.
ALERT_MIN_CONFIDENCE = env.float('ALERT_MIN_CONFIDENCE', default=0.5)
# Only scenes captured within this many days alert by WhatsApp (ONG members and admins with a phone).
# Older scenes are stored and shown on the map but alert nobody.
# TODO(prod): while detections/limits.py HACKATHON_ALERT_WINDOW_DAYS is set it overrides this (today or yesterday).
ALERT_RECENT_DAYS = env.int('ALERT_RECENT_DAYS', default=7)


def _optional(name: str, default: str) -> str | None:
    """The variable as text, or None when it is set to an empty value or 'none' (the limit is off)."""
    value = env(name, default=default).strip()
    return None if value.lower() in ('', 'none', 'off') else value


# TODO(prod): hackathon limits (detections/limits.py). Set a variable to 'none' to turn that limit off.
# Only scenes captured today or yesterday (America/Lima calendar days) alert.
_window = _optional('HACKATHON_ALERT_WINDOW_DAYS', '2')
HACKATHON_ALERT_WINDOW_DAYS = int(_window) if _window else None
# Once this many WhatsApp alerts have been sent in total, no further alert goes out.
_cap = _optional('HACKATHON_MAX_ALERT_MESSAGES', '150')
HACKATHON_MAX_ALERT_MESSAGES = int(_cap) if _cap else None
# Only alerts sent from this instant (ISO 8601 with offset) count toward the cap.
HACKATHON_CAP_SINCE = _optional('HACKATHON_CAP_SINCE', '2026-10-18T07:50:00-05:00')

# WhatsApp Cloud API, Qolca Solutions WABA (same number as the condorin.pe sign in).
WA_GRAPH_URL = env('WA_GRAPH_URL', default='https://graph.facebook.com/v23.0')
WA_TOKEN = env('WA_TOKEN', default='')
WA_PHONE_NUMBER_ID = env('WA_PHONE_NUMBER_ID', default='')
WA_WABA_ID = env('WA_WABA_ID', default='')
# UTILITY template with an image header and two URL buttons (see `manage.py create_alert_template`).
WA_ALERT_TEMPLATE = env('WA_ALERT_TEMPLATE', default='condorin_evento_v2')
# Approved AUTHENTICATION template used to confirm the person before an expediente is sent.
WA_CODE_TEMPLATE = env('WA_CODE_TEMPLATE', default='condorin_codigo')
# UTILITY template a person gets on first joining an ONG (see `manage.py create_welcome_template`). Empty: none.
WA_WELCOME_TEMPLATE = env('WA_WELCOME_TEMPLATE', default='condorin_bienvenida')
WA_TEMPLATE_LANG = env('WA_TEMPLATE_LANG', default='es')
# Header image when the crop cannot be signed (the WhatsApp preview image of condorin.pe).
WA_ALERT_FALLBACK_IMAGE = env('WA_ALERT_FALLBACK_IMAGE', default='https://www.condorin.pe/opengraph-image.jpg')
# When False, messages are logged instead of sent (local dev and tests).
WA_SEND_ENABLED = env.bool('WA_SEND_ENABLED', default=bool(WA_TOKEN))

# Google Cloud Storage: read access to the detector buckets, to pin evidence and sign links.
# GCS_CREDENTIALS_JSON is the base64 service account JSON (it must hold a private key to sign URLs).
# Without it, Application Default Credentials are used.
GCS_CREDENTIALS_JSON = env('GCS_CREDENTIALS_JSON', default='')
GCS_PROJECT_ID = env('GCS_PROJECT_ID', default='')
# Where each final expediente PDF is archived (one immutable object per confirmation). Empty: only the database copy.
GCS_EXPEDIENTES_BUCKET = env('GCS_EXPEDIENTES_BUCKET', default='')
# Lifetime of the evidence links the frontend shows and the WhatsApp header image.
GCS_SIGNED_URL_MINUTES = env.int('GCS_SIGNED_URL_MINUTES', default=60)

# An alert claimed for sending (status `sending`) longer ago than this was abandoned by a dead process;
# the retries (send_pending_alerts, the next dispatch) may claim it again.
ALERT_SENDING_STALE_MINUTES = env.int('ALERT_SENDING_STALE_MINUTES', default=10)

# Send alerts in the request thread instead of a background thread (tests, one off scripts).
ALERTS_INLINE = env.bool('ALERTS_INLINE', default=False)

# Personal expediente links sent by WhatsApp stay valid this long.
ALERT_LINK_DAYS = env.int('ALERT_LINK_DAYS', default=60)

# Email: the finished expediente is sent to the chosen authorities with the ONG member in copy.
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.sendgrid.net')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='apikey')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=15)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Ojo de Cóndor <info@qolca.org>')

# The condorin.pe server calls the /api/v1/panel routes with this secret and the signed in member's
# phone (X-Condorin-Phone). Browsers never see it. Empty turns the panel routes off.
PANEL_API_SECRET = env('PANEL_API_SECRET', default='')
# How long after an alert its WhatsApp link may also sign the member in on condorin.pe.
# The link keeps opening the expediente for ALERT_LINK_DAYS; after this window it just stops signing in.
LINK_SIGN_IN_DAYS = env.int('LINK_SIGN_IN_DAYS', default=7)
# TODO: demo only. Everyone who signs in on condorin.pe joins this ONG (empty: the oldest active ONG).
# Replace with real ONG invitations before going past the demo.
DEFAULT_ONG_ID = env.int('DEFAULT_ONG_ID', default=0)
# The role of someone who joins the default ONG that way: 'member' (full rights, the default for the live demo
# since 2026-10-18 08:30) or 'observer' (sees the panel and the alerts, never opens or signs an expediente). Admins with a
# phone always join as 'member'. Members the ONG or the admins add by hand are 'member'.
DEFAULT_ONG_JOIN_ROLE = env('DEFAULT_ONG_JOIN_ROLE', default='member')

# Redacción asistida de los hechos del expediente con Claude, vía LangChain (expedientes/redaccion.py).
# Apagada por defecto: enciéndela con EXPEDIENTE_IA_ENABLED=True y una ANTHROPIC_API_KEY.
EXPEDIENTE_IA_ENABLED = env.bool('EXPEDIENTE_IA_ENABLED', default=False)
ANTHROPIC_API_KEY = env('ANTHROPIC_API_KEY', default='')
EXPEDIENTE_IA_MODEL = env('EXPEDIENTE_IA_MODEL', default='claude-opus-5-5')
EXPEDIENTE_IA_MAX_TOKENS = env.int('EXPEDIENTE_IA_MAX_TOKENS', default=4000)
EXPEDIENTE_IA_TIMEOUT = env.int('EXPEDIENTE_IA_TIMEOUT', default=40)
