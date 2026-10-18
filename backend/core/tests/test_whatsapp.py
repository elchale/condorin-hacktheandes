"""core.whatsapp turns every malformed Meta answer into a WhatsAppError, never a KeyError or a JSON crash."""
from unittest.mock import patch

import pytest
import requests

from core import whatsapp


class FakeResponse:
    def __init__(self, status=200, body=b'', json_value=None):
        self.status_code, self.content, self._json = status, body, json_value
        self.ok = 200 <= status < 300

    def json(self):
        if self._json is None:
            raise requests.JSONDecodeError('Expecting value', '', 0)
        return self._json


@pytest.fixture
def live(settings):
    settings.WA_SEND_ENABLED = True
    settings.WA_TOKEN = 'token'
    settings.WA_PHONE_NUMBER_ID = '123'


def send(response):
    with patch.object(whatsapp.requests, 'post', return_value=response):
        return whatsapp.send_template('51936282808', 'condorin_evento_v2', [])


def test_returns_the_message_id(live):
    assert send(FakeResponse(json_value={'messages': [{'id': 'wamid.1'}]}, body=b'{}')) == 'wamid.1'


@pytest.mark.parametrize('response', [
    FakeResponse(status=502, body=b'<html>Bad gateway</html>'),        # not JSON, error status
    FakeResponse(status=200, body=b'<html>ok</html>'),                  # not JSON, 200
    FakeResponse(status=200, body=b'{}', json_value={}),                # no messages
    FakeResponse(status=200, body=b'{}', json_value={'messages': []}),  # empty messages
    FakeResponse(status=200, body=b'[]', json_value=[]),                # not an object
    FakeResponse(status=400, body=b'{}', json_value={'error': {'message': 'Invalid parameter'}}),
])
def test_malformed_answers_raise_whatsapp_error(live, response):
    with pytest.raises(whatsapp.WhatsAppError):
        send(response)


def test_network_error_is_a_whatsapp_error(live):
    with patch.object(whatsapp.requests, 'post', side_effect=requests.ConnectionError('down')):
        with pytest.raises(whatsapp.WhatsAppError):
            whatsapp.send_template('51936282808', 'condorin_evento_v2', [])
