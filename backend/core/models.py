from django.db import models


class BaseModel(models.Model):
    """Every table gets created/updated timestamps."""

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created']


class Clock(models.Model):
    """The one row (pk=1) that says what day it is for the whole API. See core/clock.py.

    With `demo_at` empty the API lives in real time. With it set, "now" is `demo_at` plus the real time
    elapsed since `set_at`, so the clock keeps ticking from the chosen instant: scenes captured after
    that instant stay hidden and the alerts of that day go out. `manage.py set_today` and the admin
    change it.
    """

    demo_at = models.DateTimeField('fecha simulada', null=True, blank=True,
                                   help_text='Vacío: hora real. Con valor: el día y la hora que la API toma como "ahora".')
    set_at = models.DateTimeField(null=True, blank=True, editable=False)
    note = models.CharField('nota', max_length=200, blank=True)

    class Meta:
        verbose_name = 'reloj'
        verbose_name_plural = 'reloj'

    def __str__(self):
        return 'Reloj'
