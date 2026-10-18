"""What the expediente page reads and writes."""
from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from core import gcs
from core.geo import coord, maps_url, utm
from detections.text import fecha_corta, fecha_larga
from ongs.models import dni_validator, ruc_validator

from .autodraft import status_label
from .codes import phone_hint
from .drafting import earlier_sightings, place_sentence
from .models import Authority, Expediente
from .services import missing_fields

EDITABLE_FIELDS = [
    'ong_name', 'ong_ruc', 'ong_address', 'notify_email', 'rep_name', 'rep_dni', 'rep_position',
    'facts', 'place_reference', 'field_observations', 'field_evidence_links', 'suspects', 'risk_notes',
    'identity_reserved', 'truth_declared',
]


class FilingInput(serializers.Serializer):
    authority = serializers.SlugRelatedField(slug_field='code', queryset=Authority.objects.filter(active=True))
    receipt_number = serializers.CharField(max_length=120)
    filed_at = serializers.DateField()


class ExpedienteUpdateSerializer(serializers.ModelSerializer):
    """PATCH body. Every field is optional, so the page can autosave one field at a time."""

    ong_ruc = serializers.CharField(max_length=11, allow_blank=True, required=False, validators=[ruc_validator])
    rep_dni = serializers.CharField(max_length=8, allow_blank=True, required=False, validators=[dni_validator])
    authorities = serializers.SlugRelatedField(
        slug_field='code', many=True, required=False, queryset=Authority.objects.filter(active=True),
    )
    filings = FilingInput(many=True, required=False)
    reopen = serializers.BooleanField(required=False)

    class Meta:
        model = Expediente
        fields = EDITABLE_FIELDS + ['authorities', 'filings', 'reopen']
        extra_kwargs = {f: {'required': False} for f in EDITABLE_FIELDS}


def _detection(d) -> dict:
    crop = None
    if d.crop_uri:
        try:
            bucket, name, generation = gcs.parse_gs_uri(d.crop_uri)
            crop = gcs.signed_url(bucket, name, d.crop_generation or generation)
        except ValueError:
            pass
    return {
        'lat': coord(d.lat),
        'lon': coord(d.lon),
        'utm': utm(float(d.lat), float(d.lon))['label'],
        'confidence': round(d.confidence, 3),
        'maps_url': maps_url(coord(d.lat), coord(d.lon)),
        'crop_url': crop,
        'crop_uri': d.crop_uri,
        'crop_sha256': d.crop_sha256,
    }


def _authority(a: Authority, selected: set, filings: dict) -> dict:
    filing = filings.get(a.pk)
    return {
        'code': a.code,
        'name': a.name,
        'kind': a.kind,
        'is_primary': a.is_primary,
        'selected': a.pk in selected,
        'submit_url': a.submit_url,
        'phone': a.phone,
        'address': a.address,
        'instructions': a.instructions,
        'max_attachment_mb': a.max_attachment_mb,
        'sends_by_email': bool(a.email),
        'filing': filing and {
            'receipt_number': filing.receipt_number,
            'filed_at': filing.filed_at,
            'filed_by': filing.filed_by.full_name if filing.filed_by else None,
        },
    }


def incident_payload(image) -> dict:
    """What the satellite saw: shared by the expediente page and the event page."""
    river = image.river
    return {
        'river': {
            'slug': river.slug, 'name': river.name, 'basin': river.basin, 'district': river.district,
            'province': river.province, 'region': river.region, 'protected_area': river.protected_area,
        },
        'place': place_sentence(river),
        'satellite': image.satellite,
        'captured_at': image.captured_at,
        'captured_at_label': fecha_larga(image.captured_at),
        'model': f'{image.model_name} {image.model_version}',
        'detections': [_detection(d) for d in image.alerting_detections()],
        'discarded': image.detections.filter(confidence__lt=settings.ALERT_MIN_CONFIDENCE).count(),
        'threshold': settings.ALERT_MIN_CONFIDENCE,
        'scene': {
            'uri': image.gs_uri,
            'md5_hash': image.md5_hash,
            'crc32c': image.crc32c,
            'size_bytes': image.size_bytes,
            'download_url': gcs.signed_url(image.bucket, image.object_name, image.generation,
                                           download_as=image.object_name.rsplit('/', 1)[-1]),
            # Shown in the page with every detection boxed; bbox is [x, y, width, height] in scene pixels.
            'preview_url': gcs.signed_url(image.bucket, image.object_name, image.generation),
            'boxes': [{'bbox': d.bbox, 'confidence': round(d.confidence, 3),
                       'alerting': d.confidence >= settings.ALERT_MIN_CONFIDENCE} for d in image.detections.all()],
        },
        'history': [
            {'captured_at': h.captured_at, 'label': fecha_corta(h.captured_at), 'satellite': h.satellite,
             'detections': h.alerting_detections().count(),
             'preview_url': gcs.signed_url(h.bucket, h.object_name, h.generation)}
            for h in earlier_sightings(image)
        ],
    }


def event_payload(alert) -> dict:
    """The event page: the incident and where the ONG's expediente stands, without opening it."""
    member, image = alert.member, alert.image
    expediente = Expediente.objects.filter(image=image, ong=member.ong).first()
    return {
        'member': {'name': member.full_name, 'first_name': member.first_name},
        'ong': {'name': member.ong.display_name},
        'incident': incident_payload(image),
        'expediente': expediente and {
            'status': expediente.status,
            'status_label': status_label(expediente),
            'folio': expediente.folio,
            'missing': len(missing_fields(expediente)) if expediente.status == Expediente.Status.DRAFT else 0,
            'updated_by': expediente.updated_by.full_name if expediente.updated_by else None,
        },
    }


def expediente_payload(expediente: Expediente, alert) -> dict:
    """Everything the expediente page needs in one response."""
    image, river, member = expediente.image, expediente.image.river, alert.member
    selected = set(expediente.authorities.values_list('pk', flat=True))
    filings = {f.authority_id: f for f in expediente.filings.select_related('filed_by')}
    # The river's authorities first, then any other the ONG may also want to file with.
    offered = list(river.authorities.filter(active=True))
    offered += [a for a in Authority.objects.filter(active=True) if a not in offered]
    pdf_path = reverse('expediente', args=[alert.token]) + '?formato=pdf'

    return {
        'member': {'name': member.full_name, 'first_name': member.first_name, 'phone_hint': phone_hint(member.phone)},
        'ong': {'name': expediente.ong.display_name},
        'expediente': {
            'id': expediente.pk,
            'folio': expediente.folio,
            'status': expediente.status,
            'status_label': expediente.get_status_display(),
            **{f: getattr(expediente, f) for f in EDITABLE_FIELDS},
            'missing': missing_fields(expediente),
            'created_by': expediente.created_by.full_name if expediente.created_by else None,
            'updated_by': expediente.updated_by.full_name if expediente.updated_by else None,
            'updated_at': expediente.updated,
            'finalized_at': expediente.finalized_at,
            'finalized_by': expediente.finalized_by.full_name if expediente.finalized_by else None,
            'pdf_url': f'https://{settings.DOMAIN}{pdf_path}',
            'pdf_sha256': expediente.pdf_sha256,
            'pdf_gcs_uri': expediente.pdf_gcs_uri,
        },
        'incident': incident_payload(image),
        'authorities': [_authority(a, selected, filings) for a in offered],
    }
