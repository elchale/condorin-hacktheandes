"""The clock in the admin: one row, change the simulated instant or clear it to return to real time."""
import threading

from django.contrib import admin, messages
from django.utils import timezone

from . import clock
from .models import Clock


@admin.register(Clock)
class ClockAdmin(admin.ModelAdmin):
    fields = ['demo_at', 'note', 'estado']
    readonly_fields = ['estado']

    def has_add_permission(self, request):
        return not Clock.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='estado')
    def estado(self, obj):
        p = clock.payload()
        kind = 'simulada' if p['simulated'] else 'real'
        return f'Hoy es {p["label"]} ({kind}), {timezone.localtime(clock.now()):%H:%M} hora de Lima.'

    def save_model(self, request, obj, form, change):
        """Saving with a date moves the clock there and sends the alerts still recent that day on a thread."""
        row = clock.set_demo(obj.demo_at, note=obj.note)
        obj.pk, obj.set_at = row.pk, row.set_at
        if row.demo_at is None:
            messages.info(request, 'La API volvió a la hora real.')
            return
        threading.Thread(target=clock.replay_today, daemon=True, name='clock-replay').start()
        messages.success(request, f'Hoy es {clock.label()}. Las alertas recientes de ese día se están enviando.')
