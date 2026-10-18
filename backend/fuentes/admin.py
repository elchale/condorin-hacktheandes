from django.contrib import admin

from .models import FeedCache


@admin.register(FeedCache)
class FeedCacheAdmin(admin.ModelAdmin):
    list_display = ('source', 'ok', 'fetched_at', 'ttl_s', 'duration_ms', 'bytes_in', 'refreshing_since', 'error')
    readonly_fields = ('payload',)
