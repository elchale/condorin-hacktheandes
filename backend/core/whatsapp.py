"""WhatsApp Cloud API: the two templates this service sends."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    pass


def send_template(phone: str, name: str, components: list[dict]) -> str:
    """Sends an approved template and returns Meta's message id.

    A 200 only means Meta accepted the message, not that it was delivered.
    With WA_SEND_ENABLED off the message is logged and a fake id is returned.
    """
    body = {
        'messaging_product': 'whatsapp',
        'to': phone,
        'type': 'template',
        'template': {'name': name, 'language': {'code': settings.WA_TEMPLATE_LANG}, 'components': components},
    }
    if not settings.WA_SEND_ENABLED:
        logger.info('whatsapp disabled, would send %s to %s: %s', name, phone, components)
        return 'dry-run'

    try:
        res = requests.post(
            f'{settings.WA_GRAPH_URL}/{settings.WA_PHONE_NUMBER_ID}/messages',
            json=body,
            headers={'Authorization': f'Bearer {settings.WA_TOKEN}'},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise WhatsAppError(str(exc)) from exc

    data = res.json() if res.content else {}
    if not res.ok:
        error = data.get('error', data)
        logger.error('whatsapp send failed %s %s', res.status_code, error)
        raise WhatsAppError(error.get('message', f'HTTP {res.status_code}') if isinstance(error, dict) else str(error))
    return data['messages'][0]['id']


def text(value: str) -> dict:
    return {'type': 'text', 'text': value}


def send_code(phone: str, code: str) -> str:
    """AUTHENTICATION template: the code goes in the body and in the copy code button."""
    return send_template(phone, settings.WA_CODE_TEMPLATE, [
        {'type': 'body', 'parameters': [text(code)]},
        {'type': 'button', 'sub_type': 'url', 'index': '0', 'parameters': [text(code)]},
    ])
