from django.contrib import admin

from .models import Authority, Expediente, Filing


@admin.register(Authority)
class AuthorityAdmin(admin.ModelAdmin):
    list_display = ['name', 'kind', 'is_primary', 'email', 'order', 'active']
    list_filter = ['kind', 'active']
    list_editable = ['order', 'active']


class FilingInline(admin.TabularInline):
    model = Filing
    extra = 0


@admin.register(Expediente)
class ExpedienteAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'ong', 'image', 'status', 'updated']
    list_filter = ['status', 'ong']
    search_fields = ['folio', 'ong__name']
    exclude = ['code_hash', 'code_member', 'code_expires_at', 'code_attempts']
    readonly_fields = ['image', 'ong', 'folio', 'finalized_by', 'finalized_at', 'pdf_sha256', 'pdf_gcs_uri',
                       'created_by', 'updated_by']
    filter_horizontal = ['authorities']
    inlines = [FilingInline]
