from django.conf import settings
from django.contrib import admin
from django.urls import path

from accounts.views import (
    CodeView,
    EnterView,
    LinkEnterView,
    MeExpedienteView,
    MeIncidentsView,
    MeView,
    SignOutView,
)
from core.views import healthz, landing, readyz
from detections.views import DetectionWebhookView
from expedientes.views import EventoView, ExpedienteSendView, ExpedienteView
from fuentes.views import FuentesRefreshView, FuentesView
from mapa.views import MapaView
from panel.views import ActivityView, LinkSignInView, PanelExpedienteView, PanelView

admin.site.site_header = 'Ojo de Cóndor'
admin.site.site_title = 'Ojo de Cóndor'

urlpatterns = [
    path('', landing, name='landing'),
    path('healthz/', healthz, name='healthz'),
    path('readyz/', readyz, name='readyz'),
    path(settings.ADMIN_URL, admin.site.urls),  # 'admin/' unless ADMIN_URL moves it

    # The detector posts here (no trailing slash: it posts exactly this path).
    path('api/v1/detections', DetectionWebhookView.as_view(), name='detections'),

    # Opened from the WhatsApp button; the token is personal to one ONG member and one incident.
    path('api/v1/expedientes/<str:token>', ExpedienteView.as_view(), name='expediente'),
    path('api/v1/eventos/<str:token>', EventoView.as_view(), name='evento'),
    path('api/v1/expedientes/<str:token>/enviar', ExpedienteSendView.as_view(), name='expediente-send'),

    # Called only by the condorin.pe server (shared secret): the ONG panel, the WhatsApp link sign in
    # and the admin live feed.
    path('api/v1/panel', PanelView.as_view(), name='panel'),
    path('api/v1/panel/incidentes/<int:image_id>/expediente', PanelExpedienteView.as_view(), name='panel-expediente'),
    path('api/v1/panel/enlace', LinkSignInView.as_view(), name='panel-link'),
    path('api/v1/panel/actividad', ActivityView.as_view(), name='panel-activity'),

    # Public map (any origin, cacheable) and the SPA sign in with a WhatsApp code and a Bearer session.
    path('api/v1/mapa', MapaView.as_view(), name='mapa'),
    path('api/v1/fuentes', FuentesView.as_view(), name='fuentes'),
    path('api/v1/fuentes/refresh', FuentesRefreshView.as_view(), name='fuentes-refresh'),
    path('api/v1/auth/codigo', CodeView.as_view(), name='auth-code'),
    path('api/v1/auth/entrar', EnterView.as_view(), name='auth-enter'),
    path('api/v1/auth/enlace', LinkEnterView.as_view(), name='auth-link'),
    path('api/v1/auth/salir', SignOutView.as_view(), name='auth-logout'),
    path('api/v1/me', MeView.as_view(), name='me'),
    path('api/v1/me/incidentes', MeIncidentsView.as_view(), name='me-incidents'),
    path('api/v1/me/incidentes/<int:image_id>/expediente', MeExpedienteView.as_view(), name='me-expediente'),
]
