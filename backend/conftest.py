"""Test defaults: no network. WhatsApp is captured, GCS is unreachable, email stays in memory."""
import pytest


@pytest.fixture(autouse=True)
def _offline(settings, monkeypatch):
    from django.core.cache import cache

    from core import gcs

    cache.clear()  # throttling counters
    settings.DETECTIONS_SHARED_SECRET = 'test-secret'
    settings.DETECTIONS_ALLOWED_SERVICE_ACCOUNTS = ['detector@condorin.iam.gserviceaccount.com']
    # The fixture scenes carry fixed October 2026 dates; the tests of the recent window set it themselves.
    settings.ALERT_RECENT_DAYS = 36500
    # The hackathon window (today or yesterday in Lima) would hide those dates too; its tests turn it back on.
    from detections import limits
    monkeypatch.setattr(limits, 'HACKATHON_ALERT_WINDOW_DAYS', None)

    def no_storage():
        raise gcs.StorageUnavailable('offline in tests')

    monkeypatch.setattr(gcs, '_client', no_storage)


@pytest.fixture
def sent(monkeypatch):
    """Every WhatsApp template 'sent' during the test, as (phone, template, components)."""
    from core import whatsapp

    calls = []

    def fake_send(phone, name, components):
        calls.append((phone, name, components))
        return f'wamid.{len(calls)}'

    monkeypatch.setattr(whatsapp, 'send_template', fake_send)
    return calls


@pytest.fixture
def river(db):
    from ongs.models import River
    return River.objects.get(slug='yaguas')  # seeded by a migration


@pytest.fixture
def ong(river):
    from ongs.models import Member, Ong

    ong = Ong.objects.create(name='Asociación Amazonía Viva', short_name='Amazonía Viva', ruc='20123456789')
    ong.rivers.add(river)
    Member.objects.create(ong=ong, full_name='María Huamán Ríos', phone='51936282808', email='maria@example.org')
    Member.objects.create(ong=ong, full_name='José Pérez', phone='51999888777')
    return ong


@pytest.fixture
def payload():
    return {
        'image': {
            'bucket': 'river-images',
            'object': 'yaguas/2026-10-15T1042Z_s1.tif',
            'generation': '1792271000',
            'river': 'yaguas',
            'satellite': 'Sentinel-1',
            'captured_at': '2026-10-15T10:42:00Z',
        },
        'model': {'name': 'dredge-detector', 'version': 'v0.3'},
        'detections': [
            {'lat': -2.7706, 'lon': -70.9512, 'confidence': 0.87, 'bbox': [412, 318, 14, 9],
             'crop_uri': 'gs://river-images/crops/yaguas_0001.png'},
        ],
    }


@pytest.fixture
def post_detection(client, django_capture_on_commit_callbacks):
    """Posts to the webhook and runs what it schedules after commit (the alert dispatch)."""
    def post(body, key='river-images/yaguas/2026-10-15T1042Z_s1.tif#1792271000', token='test-secret'):
        headers = {'HTTP_IDEMPOTENCY_KEY': key}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        with django_capture_on_commit_callbacks(execute=True):
            return client.post('/api/v1/detections', body, content_type='application/json', **headers)
    return post
