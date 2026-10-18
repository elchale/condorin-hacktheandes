"""The Claude step behind EXPEDIENTE_IA_ENABLED: off by default, and never a reason for an expediente not to open."""
import pytest

from expedientes import redaccion

DRAFT = '1. El 15 de octubre de 2026 el satélite Sentinel-1 captó una imagen del río Yaguas.'


class FakeModel:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return type('AIMessage', (), {'text': self.text})()


@pytest.fixture
def ia_on(settings):
    settings.EXPEDIENTE_IA_ENABLED = True
    settings.ANTHROPIC_API_KEY = 'sk-ant-test'


@pytest.fixture
def model(monkeypatch):
    def use(fake):
        monkeypatch.setattr(redaccion, '_model', lambda: fake)
        return fake
    return use


def test_off_by_default_keeps_the_draft_and_never_builds_a_model(settings, monkeypatch):
    assert settings.EXPEDIENTE_IA_ENABLED is False
    monkeypatch.setattr(redaccion, '_model', lambda: pytest.fail('ChatAnthropic must not be built'))
    assert redaccion.improve_facts(DRAFT, 'Río Yaguas') == DRAFT


def test_flag_without_key_stays_off(settings, monkeypatch):
    settings.EXPEDIENTE_IA_ENABLED = True
    settings.ANTHROPIC_API_KEY = ''
    monkeypatch.setattr(redaccion, '_model', lambda: pytest.fail('ChatAnthropic must not be built'))
    assert redaccion.improve_facts(DRAFT, 'Río Yaguas') == DRAFT


def test_on_returns_what_claude_wrote(ia_on, model):
    fake = model(FakeModel(text='  1. Hechos redactados por Claude.  '))
    assert redaccion.improve_facts(DRAFT, 'Río Yaguas, Loreto') == '1. Hechos redactados por Claude.'
    (messages,) = fake.calls
    assert messages[0]['role'] == 'system' and 'no inventes' in messages[0]['content']
    assert messages[1]['role'] == 'user' and DRAFT in messages[1]['content'] and 'Río Yaguas, Loreto' in messages[1]['content']


def test_failure_falls_back_to_the_draft(ia_on, model, caplog):
    model(FakeModel(error=RuntimeError('rate limited')))
    assert redaccion.improve_facts(DRAFT, 'Río Yaguas') == DRAFT
    assert 'keeping the deterministic draft' in caplog.text


def test_empty_answer_falls_back_to_the_draft(ia_on, model):
    model(FakeModel(text=''))
    assert redaccion.improve_facts(DRAFT, 'Río Yaguas') == DRAFT


def test_empty_draft_is_not_sent(ia_on, model):
    fake = model(FakeModel(text='algo'))
    assert redaccion.improve_facts('', 'Río Yaguas') == ''
    assert fake.calls == []


@pytest.mark.django_db
def test_first_tap_uses_claude_when_enabled(client, post_detection, payload, ong, sent, ia_on, model):
    from detections.models import Alert

    model(FakeModel(text='1. Hechos redactados por Claude.'))
    post_detection(payload)
    alert = Alert.objects.select_related('member').get(member__phone='51936282808')

    exp = client.get(f'/api/v1/expedientes/{alert.token}').json()['expediente']
    assert exp['facts'] == '1. Hechos redactados por Claude.'
    assert exp['place_reference'].startswith('Río Yaguas')


@pytest.mark.django_db
def test_claude_is_called_once_per_expediente(client, post_detection, payload, ong, sent, ia_on, model):
    from detections.models import Alert

    fake = model(FakeModel(text='1. Hechos redactados por Claude.'))
    post_detection(payload)
    for alert in Alert.objects.select_related('member'):  # two members of the same ONG tap the alert
        assert client.get(f'/api/v1/expedientes/{alert.token}').status_code == 200
    assert len(fake.calls) == 1
