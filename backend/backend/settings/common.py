"""Core Django settings for the Ojo de Cóndor API (api.condorin.pe).

The API has no user accounts. Access works three ways:
- the detector authenticates the webhook with a Google ID token or a shared secret;
- each ONG member gets a personal link token by WhatsApp that opens their expediente;
- staff use the Django admin with a username and password.
"""
from .env import BASE_DIR, env

SECRET_KEY = env('DJANGO_SECRET_KEY')

DEBUG = env('DEBUG', default=False)

# Public host of this API, without scheme.
DOMAIN = env('DOMAIN', default='api.condorin.pe')

# Public URL of the Next.js app that hosts the expediente pages.
FRONTEND_URL = env('FRONTEND_URL', default='https://condorin.pe').rstrip('/')

ALLOWED_HOSTS = [DOMAIN, 'localhost', '127.0.0.1']

# Other hosts that serve the API, comma separated (e.g. the Cloud Run URL: condorin-api-xxxx.a.run.app).
_extra_hosts = env.list('EXTRA_ALLOWED_HOSTS', default=[])
ALLOWED_HOSTS += _extra_hosts

# The admin login posts a form, so every host that serves it must be a trusted origin ('.run.app' → '*.run.app').
CSRF_TRUSTED_ORIGINS = [f'https://{DOMAIN}'] + [f'https://*{h}' if h.startswith('.') else f'https://{h}'
                                                for h in _extra_hosts]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',

    'core',
    'accounts',
    'ongs',
    'detections',
    'expedientes',
    'panel',
    'mapa',
    'fuentes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Cloud Run does not compress: gzip every response above 200 bytes when the client accepts it.
    'django.middleware.gzip.GZipMiddleware',
    'core.middleware.RequestIdMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # GET /api/v1/mapa is public: its preflight is answered for any origin before corsheaders sees it.
    'mapa.middleware.PublicCorsMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.AccessLogsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

# Neon Postgres, shared with the Next.js app. Django owns every migration.
DATABASES = {'default': env.db_url('DATABASE_URL')}
# Persistent connections: the TLS handshake to Neon costs more than most queries. Health checks drop a
# connection Neon closed (compute suspended) before it is reused.
DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=600)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
# Fail fast instead of hanging when Neon is unreachable (libpq waits without limit by default), so the
# migrate at container start or a request errors out in seconds and the logs say why.
if 'postgresql' in DATABASES['default']['ENGINE']:
    DATABASES['default'].setdefault('OPTIONS', {}).setdefault(
        'connect_timeout', env.int('DB_CONNECT_TIMEOUT', default=10))
# Neon's pooler (PgBouncer) does not support server side cursors.
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
# pytest creates and drops its own database on the same server, never touching this one.
DATABASES['default']['TEST'] = {'NAME': env('TEST_DB_NAME', default='test_condorin')}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

LANGUAGE_CODE = 'es-pe'
TIME_ZONE = 'America/Lima'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# The browser only talks to this API from the Next.js app.
CORS_ALLOWED_ORIGINS = [FRONTEND_URL, 'https://www.condorin.pe'] + [
    o.strip() for o in env('ADDITIONAL_CORS_ORIGINS', default='').split(',') if o.strip()
]
# Origins that change per deploy, as regexes (e.g. Vercel previews: ^https://condorin-[a-z0-9-]+\.vercel\.app$).
CORS_ALLOWED_ORIGIN_REGEXES = env.list('CORS_ALLOWED_ORIGIN_REGEXES', default=[])
if DEBUG:
    # Local frontends: the Vite map (5173) and Next (3000). GET /api/v1/mapa allows any origin by itself.
    CORS_ALLOWED_ORIGINS += ['http://localhost:5173', 'http://localhost:3000']
# The browser reads the PDF's file name (Content-Disposition) and the request id.
CORS_EXPOSE_HEADERS = ['x-request-id', 'content-disposition']
# django-cors-headers' default headers already include authorization and content-type.

# `default` is shared by every instance (a table in the same Postgres, created by core 0002_cache_table): sign in
# codes, attempt counters and their throttles. `local` is process memory for payload caches, the clock row and
# the high volume throttles (core/cache.py, core/throttling.py).
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache',
        # Culling at the default 300 rows would drop live resend locks and attempt counters.
        'OPTIONS': {'MAX_ENTRIES': 50000},
    },
    'local': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'condorin-local'},
}

REST_FRAMEWORK = {
    # No sessions or JWT: callers prove who they are with the link token or the webhook bearer.
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'UNAUTHENTICATED_USER': None,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_THROTTLE_CLASSES': ['core.throttling.ScopedThrottle'],
    # Cloud Run's front end is the one proxy: it appends the caller's address to X-Forwarded-For, so the client
    # is the last entry and anything the caller wrote before it is ignored. Behind a load balancer, set 2.
    'NUM_PROXIES': env.int('NUM_PROXIES', default=1),
    'DEFAULT_THROTTLE_RATES': {
        'expediente': '120/minute',
        'expediente_send': '30/hour',
        'panel': '600/minute',
        'panel_link': '60/minute',
        'mapa': '600/minute',
        'fuentes': '600/minute',
        # TODO(prod): back to 10/hour and 30/hour. Raised for the live pitch, where the audience signs up
        # together from the venue's one public IP; the per phone limits below still stop spam.
        'auth_code': '200/hour',
        'auth_enter': '300/hour',
        # Per phone, from any IP (core.throttling.PhoneThrottle), on top of the per IP limits above.
        'auth_code_phone': '6/hour',
        'auth_enter_phone': '20/hour',
        'me': '300/minute',
    },
    'EXCEPTION_HANDLER': 'core.exceptions.envelope_exception_handler',
}

# Security headers
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT', default=True)
    # The health probe comes from inside the platform over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r'^healthz/$', r'^readyz/$']
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Where the Django admin lives. Default 'admin/' (the staff bookmarks); set ADMIN_URL to move it off the
# path every scanner tries first.
ADMIN_URL = env('ADMIN_URL', default='admin/').strip('/') + '/'
# The secret of POST /api/v1/fuentes/refresh (the refresh-feeds workflow). Empty: PANEL_API_SECRET, as before.
FUENTES_REFRESH_SECRET = env('FUENTES_REFRESH_SECRET', default='')

# How long the anonymous GET /api/v1/mapa payload stays in the process cache.
MAPA_CACHE_SECONDS = env.int('MAPA_CACHE_SECONDS', default=30)
# How long the encoded GET /api/v1/fuentes body stays in the process cache (the feeds refresh in the background).
FUENTES_CACHE_SECONDS = env.int('FUENTES_CACHE_SECONDS', default=60)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '{levelname} {asctime} {name} {message}', 'style': '{'}},
    'filters': {'redact_tokens': {'()': 'core.middleware.RedactTokensFilter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain', 'filters': ['redact_tokens']}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}
