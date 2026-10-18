"""The denuncia an ONG prepares from an alert, and where it was filed."""
from django.db import models

from core.models import BaseModel


class Authority(BaseModel):
    """Where a denuncia can be filed. Managed in the admin; seeded with the verified channels."""

    class Kind(models.TextChoices):
        FISCALIA = 'fiscalia', 'Fiscalía (FEMA)'
        OEFA = 'oefa', 'OEFA'
        SERNANP = 'sernanp', 'SERNANP'
        POLICIA = 'policia', 'Policía'
        MARINA = 'marina', 'Marina (DICAPI)'
        GOBIERNO_REGIONAL = 'gore', 'Gobierno Regional'
        OTRA = 'otra', 'Otra'

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    is_primary = models.BooleanField(
        'principal', default=False,
        help_text='Se marca por defecto en el expediente. La Fiscalía es la vía principal para minería ilegal.',
    )
    submit_url = models.URLField('enlace para presentar', blank=True)
    email = models.EmailField(
        blank=True, help_text='Solo si la autoridad confirmó que recibe denuncias por correo; se le envía el PDF.',
    )
    phone = models.CharField('teléfono', max_length=60, blank=True)
    address = models.CharField('dirección', max_length=255, blank=True)
    instructions = models.TextField('cómo presentar', blank=True)
    max_attachment_mb = models.PositiveSmallIntegerField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'autoridad'
        verbose_name_plural = 'autoridades'

    def __str__(self):
        return self.name


class Expediente(BaseModel):
    """One per image and ONG. Every member of the ONG who taps the alert opens the same one.

    Lifecycle: `draft` while the ONG fills it in, `ready` once a member confirms it with the
    WhatsApp code (the final PDF gets a folio and is emailed), `filed` once a filing receipt
    from an authority is recorded.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Borrador'
        READY = 'ready', 'Listo para presentar'
        FILED = 'filed', 'Presentado'

    image = models.ForeignKey('detections.SatelliteImage', on_delete=models.PROTECT, related_name='expedientes')
    ong = models.ForeignKey('ongs.Ong', on_delete=models.PROTECT, related_name='expedientes')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    folio = models.CharField(max_length=20, unique=True, null=True, blank=True)

    # Denunciante. Prefilled from the ONG and the member; edits are copied back so they are asked once.
    ong_name = models.CharField('razón social', max_length=200, blank=True)
    ong_ruc = models.CharField('RUC', max_length=11, blank=True)
    ong_address = models.CharField('domicilio', max_length=255, blank=True)
    notify_email = models.EmailField('correo para notificaciones', blank=True)
    rep_name = models.CharField('representante', max_length=160, blank=True)
    rep_dni = models.CharField('DNI del representante', max_length=8, blank=True)
    rep_position = models.CharField('cargo del representante', max_length=120, blank=True)
    rep_phone = models.CharField('teléfono del representante', max_length=15, blank=True)

    # Hechos. `facts` starts as a draft written from the detection; the rest is what only the ONG knows.
    facts = models.TextField('hechos', blank=True)
    place_reference = models.CharField('referencia del lugar', max_length=255, blank=True)
    field_observations = models.TextField('observaciones en campo', blank=True)
    field_evidence_links = models.TextField('enlaces a fotos o videos', blank=True)
    suspects = models.TextField('presuntos responsables', blank=True)
    risk_notes = models.TextField('riesgos para la comunidad', blank=True)
    identity_reserved = models.BooleanField('solicita reserva de identidad', default=False)
    truth_declared = models.BooleanField('declara que los hechos son verdaderos', default=False)
    authorities = models.ManyToManyField(Authority, blank=True, related_name='expedientes')

    # True when Ojo de Cóndor drafted it on its own at ingest (no member tapped anything yet).
    auto_created = models.BooleanField('borrador automático', default=False)
    created_by = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, related_name='+')
    updated_by = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, related_name='+')

    # Final document, set when a member confirms with the WhatsApp code.
    finalized_by = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    finalized_at = models.DateTimeField(null=True, blank=True)
    pdf = models.BinaryField(null=True, blank=True, editable=False)
    pdf_sha256 = models.CharField(max_length=64, blank=True)
    # The same PDF archived in GCS_EXPEDIENTES_BUCKET as gs://bucket/object#generation; blank if it could not be.
    pdf_gcs_uri = models.CharField('PDF en Cloud Storage', max_length=1100, blank=True)

    # Pending WhatsApp confirmation code (HMAC of the code, never the code itself).
    code_hash = models.CharField(max_length=64, blank=True)
    code_member = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    code_expires_at = models.DateTimeField(null=True, blank=True)
    code_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'expediente'
        constraints = [
            models.UniqueConstraint(fields=['image', 'ong'], name='expediente_unique_per_image_ong'),
        ]

    def __str__(self):
        return self.folio or f'Borrador {self.pk} ({self.ong})'


class Filing(BaseModel):
    """Proof that the expediente was filed with an authority (the número de registro or cargo)."""

    expediente = models.ForeignKey(Expediente, on_delete=models.CASCADE, related_name='filings')
    authority = models.ForeignKey(Authority, on_delete=models.PROTECT, related_name='filings')
    receipt_number = models.CharField('número de registro', max_length=120)
    filed_at = models.DateField('fecha de presentación')
    filed_by = models.ForeignKey('ongs.Member', on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        ordering = ['filed_at']
        verbose_name = 'presentación'
        verbose_name_plural = 'presentaciones'
        constraints = [
            models.UniqueConstraint(fields=['expediente', 'authority'], name='filing_unique_per_authority'),
        ]

    def __str__(self):
        return f'{self.authority}: {self.receipt_number}'
