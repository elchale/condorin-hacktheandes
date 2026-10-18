from django.contrib import admin

from .models import Alert, Detection, SatelliteImage


class DetectionInline(admin.TabularInline):
    model = Detection
    extra = 0
    can_delete = False
    readonly_fields = ['index', 'lat', 'lon', 'confidence', 'bbox', 'crop_uri', 'crop_generation', 'crop_sha256']


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0
    can_delete = False
    fields = ['member', 'status', 'attempts', 'sent_at', 'opened_at', 'error']
    readonly_fields = fields


@admin.register(SatelliteImage)
class SatelliteImageAdmin(admin.ModelAdmin):
    list_display = ['river', 'captured_at', 'satellite', 'model_version', 'created']
    list_filter = ['river', 'satellite']
    date_hierarchy = 'captured_at'
    readonly_fields = [f.name for f in SatelliteImage._meta.fields]
    inlines = [DetectionInline, AlertInline]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['image', 'member', 'status', 'attempts', 'sent_at', 'opened_at']
    list_filter = ['status']
    search_fields = ['member__full_name', 'member__phone']
    readonly_fields = ['image', 'member', 'token', 'wa_message_id', 'sent_at', 'opened_at', 'attempts', 'error']
