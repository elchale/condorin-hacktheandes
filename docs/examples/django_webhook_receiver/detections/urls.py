from django.urls import path

from .views import detections_webhook

urlpatterns = [
    path("api/v1/detections", detections_webhook, name="detections-webhook"),
]
