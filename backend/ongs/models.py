"""ONGs, the people who get the alerts, and the rivers each ONG watches."""
from django.core.validators import RegexValidator
from django.db import models

from core.models import BaseModel
from core.phone import phone_validator

ruc_validator = RegexValidator(r'^\d{11}$', 'El RUC tiene 11 dígitos.')
dni_validator = RegexValidator(r'^\d{8}$', 'El DNI tiene 8 dígitos.')


class River(BaseModel):
    """A river the detector watches. `slug` is the `image.river` value the webhook sends."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    basin = models.CharField('cuenca', max_length=120, blank=True)
    district = models.CharField('distrito', max_length=120, blank=True)
    province = models.CharField('provincia', max_length=120, blank=True)
    region = models.CharField('región', max_length=120, blank=True)
    protected_area = models.CharField(
        'área natural protegida', max_length=160, blank=True,
        help_text='Por ejemplo "Parque Nacional Yaguas". Vacío si el río está fuera de un ANP.',
    )
    authorities = models.ManyToManyField(
        'expedientes.Authority', blank=True, related_name='rivers',
        help_text='Autoridades a las que se sugiere presentar la denuncia.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'río'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        created = self._state.adding
        super().save(*args, **kwargs)
        if created:
            # A new river is watched by the internal team from the start, so the admins hear about it.
            for team in Ong.objects.filter(internal=True):
                team.rivers.add(self)


class Ong(BaseModel):
    """An organisation that receives the alerts for its rivers and files the denuncias."""

    name = models.CharField('razón social', max_length=200)
    short_name = models.CharField('nombre corto', max_length=80, blank=True)
    ruc = models.CharField(max_length=11, blank=True, validators=[ruc_validator])
    address = models.CharField('domicilio', max_length=255, blank=True)
    email = models.EmailField('correo para notificaciones', blank=True)
    rivers = models.ManyToManyField(River, blank=True, related_name='ongs')
    active = models.BooleanField(default=True)
    internal = models.BooleanField(
        'interna', default=False,
        help_text='El equipo de Ojo de Cóndor: vigila todos los ríos y reúne a los administradores con WhatsApp. '
                  'No aparece en el mapa público ni en el panel.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'ONG'
        verbose_name_plural = 'ONGs'

    def __str__(self):
        return self.short_name or self.name

    @property
    def display_name(self):
        return self.short_name or self.name


class Member(BaseModel):
    """Someone at an ONG who receives the WhatsApp alerts.

    Only `full_name` and `phone` are needed to get alerts. The rest is asked once,
    in the expediente, and remembered for the next one.

    `role`: a `member` (added by the ONG or the admins) opens, edits and files expedientes. An `observer`
    (anyone who joined the default ONG by signing in, see panel.services.member_for_phone) sees the panel,
    the incidents and the alerts, and reads the ONG's expediente without the signer's personal data.
    """

    class Role(models.TextChoices):
        MEMBER = 'member', 'Miembro'
        OBSERVER = 'observer', 'Observador'

    ong = models.ForeignKey(Ong, on_delete=models.CASCADE, related_name='members')
    full_name = models.CharField('nombre completo', max_length=160)
    phone = models.CharField('WhatsApp', max_length=15, validators=[phone_validator])
    dni = models.CharField('DNI', max_length=8, blank=True, validators=[dni_validator])
    email = models.EmailField('correo', blank=True)
    position = models.CharField('cargo', max_length=120, blank=True)
    is_legal_representative = models.BooleanField('representante legal', default=False)
    active = models.BooleanField(default=True)
    # Signed into every SPA session of this phone; "Salir" (POST /api/v1/auth/salir) bumps it, which ends them all.
    role = models.CharField(
        'rol', max_length=10, choices=Role.choices, default=Role.MEMBER, db_default=Role.MEMBER,
        help_text='Observador: ve el panel y las alertas, pero no abre, edita ni envía expedientes.',
    )
    session_version = models.PositiveIntegerField('versión de sesión', default=0, db_default=0, editable=False)

    class Meta:
        ordering = ['ong', 'full_name']
        verbose_name = 'miembro'
        constraints = [
            models.UniqueConstraint(fields=['ong', 'phone'], name='member_unique_phone_per_ong'),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.ong})'

    @property
    def can_act(self) -> bool:
        """May open, edit and finalize expedientes and record filings (observers only read)."""
        return self.role == self.Role.MEMBER

    @property
    def first_name(self):
        return self.full_name.split()[0] if self.full_name else ''
