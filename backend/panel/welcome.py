"""The WhatsApp welcome a person gets when they first join an ONG through a condorin.pe sign in.

Only a greeting: joining never sends an event. Events go out when the detector reports a recent scene,
or by hand with `manage.py send_event`.
"""
import logging
import threading

from django.conf import settings

from core import whatsapp

logger = logging.getLogger(__name__)

# The body must match the approved template exactly (see `manage.py create_welcome_template`). No variables.
WELCOME_BODY = (
    'Te damos la bienvenida a Ojo de Cóndor. Tu cuenta quedó activa con este número.\n\n'
    'Cuando detectemos posible minería ilegal en los ríos que vigila tu organización, te avisaremos por aquí '
    'con la evidencia y el expediente listo para revisar.'
)
WELCOME_BUTTON = 'Abrir mi panel'


def welcome_template_definition() -> dict:
    """Body for POST /{WABA_ID}/message_templates."""
    return {
        'name': settings.WA_WELCOME_TEMPLATE,
        'language': settings.WA_TEMPLATE_LANG,
        'category': 'UTILITY',
        'components': [
            {'type': 'BODY', 'text': WELCOME_BODY},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'URL', 'text': WELCOME_BUTTON, 'url': f'{settings.FRONTEND_URL}/panel'},
            ]},
        ],
    }


def send_welcome(phone: str) -> None:
    """Sends the welcome on a thread, so the sign in does not wait for Meta. A failure is only logged."""
    if not settings.WA_WELCOME_TEMPLATE:
        return
    from detections.limits import cap_reached
    if cap_reached():
        # TODO(prod): hackathon cap (detections/limits.py): once it is used up, no WhatsApp goes out at all.
        logger.warning('panel: hackathon WhatsApp cap reached, no welcome to %s', phone)
        return

    def run():
        try:
            whatsapp.send_template(phone, settings.WA_WELCOME_TEMPLATE, [])
        except whatsapp.WhatsAppError as exc:
            logger.warning('panel: welcome to %s failed: %s', phone, exc)

    if getattr(settings, 'ALERTS_INLINE', False):
        run()
        return
    threading.Thread(target=run, daemon=True, name=f'welcome-{phone}').start()
