from django.db import models

from core.models import BaseModel


class FeedCache(BaseModel):
    """The last payload of one open data source (one row per source id).

    `fetched_at` is the time of the last successful fetch; a failed fetch keeps the old payload and
    only records `error`. `refreshing_since` marks a refresh in flight so several instances do not
    hit the same upstream at once (a claim older than five minutes is considered dead).
    """

    source = models.CharField(max_length=40, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    ttl_s = models.PositiveIntegerField(default=3600)
    refreshing_since = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    bytes_in = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['source']
        verbose_name = 'fuente en caché'
        verbose_name_plural = 'fuentes en caché'

    def __str__(self):
        return self.source
