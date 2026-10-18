"""Store a webhook delivery, then alert every member of the ONGs that watch that river.

Only a recent scene alerts (captured within ALERT_RECENT_DAYS; TODO(prod): while the hackathon limits in
detections/limits.py are set, today or yesterday in Lima, and at most 50 WhatsApp alerts in total).
Its recipients are the active members of every ONG watching the river plus the admins with a phone,
through the hidden internal ONG (ongs.team). Older or simulated scenes are stored and shown on the map but alert nobody.

Delivery is at least once on the detector side, so storing is idempotent on the
Idempotency-Key and every alert row is unique per (image, member): a retry never
messages anyone twice.
"""
import hashlib
import logging
import threading

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone

from core import clock, gcs, whatsapp
from expedientes.autodraft import create_drafts
from ongs.models import Member, River
from ongs.team import sync_internal_team

from . import limits
from .models import Alert, Detection, SatelliteImage, sending_stale_before
from .text import alert_template_components

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5

# Why a scene did or did not alert, as the webhook reports it.
ALERTED = 'alerted'
OLD_SCENE = 'old_scene'
SIMULATED = 'simulated'
BELOW_THRESHOLD = 'below_threshold'
NO_RECIPIENTS = 'no_recipients'
CAPPED = 'capped'  # TODO(prod): hackathon cap, see detections/limits.py

# What the automatic sends (dispatch, retries, the clock replay) may claim: pending or failed rows.
RETRIABLE = [Alert.Status.PENDING, Alert.Status.FAILED]


def is_recent(image: SatelliteImage) -> bool:
    """Captured within the alert window of the API's clock (core.clock: real, or the demo day).

    TODO(prod): while limits.HACKATHON_ALERT_WINDOW_DAYS is set it overrides ALERT_RECENT_DAYS (today or yesterday in Lima).
    """
    return image.captured_at >= limits.window_start(clock.now())


def is_simulated(image: SatelliteImage) -> bool:
    """A payload marked as demo or simulated (simulate_detection marks its own) never notifies anyone."""
    payload = image.payload if isinstance(image.payload, dict) else {}
    return bool(payload.get('simulated') or payload.get('demo'))


def may_notify(image: SatelliteImage) -> bool:
    return is_recent(image) and not is_simulated(image)


def alert_reason(image: SatelliteImage) -> str:
    if is_simulated(image):
        return SIMULATED
    if not image.alerting_detections().exists():
        return BELOW_THRESHOLD
    if not is_recent(image):
        return OLD_SCENE
    alerts = image.alerts.exclude(status=Alert.Status.PANEL)
    if not alerts.exists():
        return NO_RECIPIENTS
    if not alerts.filter(status=Alert.Status.SENT).exists() and (
            alerts.filter(status=Alert.Status.CAPPED).exists() or limits.cap_reached()):
        # Nothing for this scene went out, and nothing can: the hackathon cap is used up.
        return CAPPED
    return ALERTED


def recipients(river: River) -> list[Member]:
    """Active members of the active ONGs watching the river, then the admins (internal team).

    An admin who is also a member of a watching ONG gets one message, as that member.
    """
    sync_internal_team()
    members = list(Member.objects.filter(active=True, ong__active=True, ong__rivers=river)
                   .select_related('ong').order_by('ong__internal', 'pk').distinct())
    chosen, phones = [], set()
    for m in members:
        if m.ong.internal and m.phone in phones:
            continue
        phones.add(m.phone)
        chosen.append(m)
    return chosen


def queue_alerts(image: SatelliteImage) -> int:
    """An alert row for every current recipient of the river who has none for this scene yet. Returns how many.

    Used when the clock is moved to the scene's day (core.clock.replay_today); the rows start pending and
    process_image sends them. Members already alerted keep their row, so nobody is messaged twice.
    """
    if is_simulated(image) or not image.alerting_detections().exists():
        return 0
    created = 0
    for member in recipients(image.river):
        _, new = Alert.objects.get_or_create(image=image, member=member)
        created += int(new)
    return created


def idempotency_key(header_value: str, image: dict) -> str:
    return (header_value or f"{image['bucket']}/{image['object']}#{image['generation']}")[:512]


@transaction.atomic
def ingest(data: dict, key: str, raw: dict) -> tuple[SatelliteImage, bool]:
    """Stores the validated `data` (and the `raw` body as received). Returns (image, created).

    A repeated key returns the stored image untouched.
    """
    existing = SatelliteImage.objects.filter(idempotency_key=key).first()
    if existing:
        return existing, False

    img = data['image']
    river, _ = River.objects.get_or_create(slug=img['river'], defaults={'name': img['river'].replace('-', ' ').title()})
    try:
        with transaction.atomic():
            image = SatelliteImage.objects.create(
                idempotency_key=key,
                river=river,
                bucket=img['bucket'],
                object_name=img['object'],
                generation=img['generation'],
                satellite=img['satellite'],
                captured_at=img['captured_at'],
                model_name=data['model']['name'],
                model_version=data['model']['version'],
                payload=raw,
            )
    except IntegrityError:
        # A concurrent delivery of the same key won the race.
        return SatelliteImage.objects.get(idempotency_key=key), False

    Detection.objects.bulk_create([
        Detection(image=image, index=i, lat=d['lat'], lon=d['lon'], confidence=d['confidence'],
                  bbox=d['bbox'], crop_uri=d.get('crop_uri', ''))
        for i, d in enumerate(data['detections'])
    ])

    if image.alerting_detections().exists():
        if is_simulated(image):
            logger.info('detections: image %s is marked simulated, nobody was alerted', image.pk)
        elif not is_recent(image):
            logger.info('detections: image %s was captured %s, older than %s, nobody was alerted',
                        image.pk, image.captured_at, limits.window_label())
        else:
            members = recipients(river)
            Alert.objects.bulk_create([Alert(image=image, member=m) for m in members])
            if not members:
                logger.warning('detections: river %s has no ONG members or admins, nobody was alerted', river.slug)
        # Every scene, recent or old, gets its prefilled draft per watching ONG. Silent: nothing is sent.
        create_drafts(image)

    transaction.on_commit(lambda: dispatch(image.pk))
    return image, True


def dispatch(image_id: int) -> None:
    """Runs after the webhook responds, on a thread, or inline when ALERTS_INLINE or the thread cannot start."""
    if getattr(settings, 'ALERTS_INLINE', False):
        _run_inline(image_id)
        return
    try:
        threading.Thread(target=_run_in_thread, args=(image_id,), daemon=True, name=f'alerts-{image_id}').start()
    except RuntimeError:
        logger.warning('detections: could not start the alert thread for image %s, sending inline', image_id)
        _run_inline(image_id)


def _run_inline(image_id: int) -> None:
    try:
        process_image(image_id)
    except Exception:
        logger.exception('detections: inline alert dispatch crashed for image %s', image_id)


def _run_in_thread(image_id: int) -> None:
    try:
        process_image(image_id)
    except Exception:
        logger.exception('detections: alert dispatch crashed for image %s', image_id)
    finally:
        close_old_connections()


def process_image(image_id: int) -> None:
    image = SatelliteImage.objects.select_related('river').get(pk=image_id)
    pin_evidence(image)
    if not may_notify(image):
        # Retries and late dispatches never message about an old or simulated scene.
        logger.info('detections: image %s is old or simulated, its pending alerts are not sent', image.pk)
        return
    for alert in retriable(image.alerts.all()).select_related('member'):
        send_alert_safely(alert)
    capped = image.alerts.filter(status=Alert.Status.CAPPED).count()
    if capped:
        logger.warning('detections: hackathon cap of %s WhatsApp alerts reached, %s alerts of image %s were not sent',
                       limits.HACKATHON_MAX_ALERT_MESSAGES, capped, image.pk)


def pin_evidence(image: SatelliteImage) -> None:
    """Record GCS's own hashes for the scene and the SHA-256 of each crop, so the evidence is fixed."""
    if not image.md5_hash:
        try:
            meta = gcs.object_metadata(image.bucket, image.object_name, image.generation)
            image.md5_hash, image.crc32c, image.size_bytes = meta['md5_hash'], meta['crc32c'], meta['size_bytes']
            image.save(update_fields=['md5_hash', 'crc32c', 'size_bytes', 'updated'])
        except gcs.StorageUnavailable as exc:
            logger.warning('detections: could not read scene metadata for %s: %s', image.gs_uri, exc)

    for det in image.detections.filter(crop_sha256='').exclude(crop_uri=''):
        try:
            bucket, name, generation = gcs.parse_gs_uri(det.crop_uri)
            content, read_generation = gcs.download(bucket, name, generation)
        except (ValueError, gcs.StorageUnavailable) as exc:
            logger.warning('detections: could not read crop %s: %s', det.crop_uri, exc)
            continue
        det.crop_sha256 = hashlib.sha256(content).hexdigest()
        det.crop_generation = read_generation
        det.save(update_fields=['crop_sha256', 'crop_generation', 'updated'])


def header_image_url(image: SatelliteImage) -> str:
    """Signed link to the crop of the strongest detection; the brand image when there is none."""
    best = image.alerting_detections().exclude(crop_uri='').order_by('-confidence').first()
    if best:
        try:
            bucket, name, generation = gcs.parse_gs_uri(best.crop_uri)
            url = gcs.signed_url(bucket, name, best.crop_generation or generation, minutes=24 * 60)
            if url:
                return url
        except ValueError:
            pass
    return settings.WA_ALERT_FALLBACK_IMAGE


def abandoned() -> Q:
    """Rows a dead process left `sending`."""
    return Q(status=Alert.Status.SENDING, updated__lt=sending_stale_before())


def retriable(alerts):
    """The alerts an automatic send may still try: pending, failed or abandoned, with attempts left."""
    return alerts.filter(Q(status__in=RETRIABLE) | abandoned(), attempts__lt=MAX_ATTEMPTS)


def send_alert_safely(alert: Alert, **kwargs) -> None:
    """send_alert for one recipient of a loop: whatever breaks is recorded on that alert, the others still go."""
    try:
        send_alert(alert, **kwargs)
    except Exception as exc:
        logger.exception('detections: alert %s crashed while sending', alert.pk)
        record_failure(alert, exc)


def record_failure(alert: Alert, exc: Exception) -> None:
    # Counted as an attempt, so a recipient that always breaks stops being retried after MAX_ATTEMPTS.
    Alert.objects.filter(pk=alert.pk).exclude(status=Alert.Status.SENT).update(
        status=Alert.Status.FAILED, error=f'{type(exc).__name__}: {exc}'[:2000],
        attempts=F('attempts') + 1, updated=timezone.now())


def send_alert(alert: Alert, manual: bool = False) -> None:
    """Sends one alert, by one sender at a time: the row is claimed (`sending`) with one conditional UPDATE, so
    two threads, instances or a command racing for the same alert never both message the member.

    Automatic sends only claim pending, failed or abandoned rows. `manual` (manage.py send_event) may claim any
    row not being sent right now, a sent one included when the operator asked to resend.
    """
    image = alert.image
    best = image.alerting_detections().order_by('-confidence').first()
    if best is None:
        return

    components = alert_template_components(
        member=alert.member,
        image=image,
        count=image.alerting_detections().count(),
        header_url=header_image_url(image),
        token=alert.token,
        lat=best.lat,
        lon=best.lon,
    )
    claimable = Q(status__in=RETRIABLE) | abandoned()
    if manual:
        claimable = ~Q(status=Alert.Status.SENDING) | abandoned()
    row = Alert.objects.filter(claimable, pk=alert.pk)
    with transaction.atomic():
        # One sender at a time decides on the cap, in every process; claimed rows count as used slots.
        limits.lock_cap()
        if limits.cap_reached(include_in_flight=True):
            # TODO(prod): hackathon cap. Never retried: the automatic sends only claim pending or failed rows.
            row.exclude(status=Alert.Status.SENT).update(
                status=Alert.Status.CAPPED, error=limits.CAPPED_ERROR, updated=timezone.now())
            alert.refresh_from_db()
            return
        if row.update(status=Alert.Status.SENDING, updated=timezone.now()) != 1:
            logger.info('detections: alert %s is already being sent or was sent, skipped', alert.pk)
            alert.refresh_from_db()
            return

    done = Alert.objects.filter(pk=alert.pk, status=Alert.Status.SENDING)
    try:
        message_id = whatsapp.send_template(alert.member.phone, settings.WA_ALERT_TEMPLATE, components)
    except whatsapp.WhatsAppError as exc:
        done.update(status=Alert.Status.FAILED, error=str(exc)[:2000], attempts=F('attempts') + 1,
                    updated=timezone.now())
    else:
        done.update(status=Alert.Status.SENT, error='', wa_message_id=message_id, sent_at=clock.now(),
                    attempts=F('attempts') + 1, updated=timezone.now())
    alert.refresh_from_db()
