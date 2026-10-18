"""Tables the Next.js app (condorin.pe) reads and writes through Prisma.

Django owns the schema and the migrations; Prisma only maps onto these tables (see
condorin/prisma/schema.prisma). Columns the frontend inserts without a value carry a
database default (`db_default`) because Prisma does not run Django's Python defaults.
"""
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Now

phone_validator = RegexValidator(r'^\d{10,15}$', 'Solo dígitos con código de país, por ejemplo 51987654321.')


class Member(models.Model):
    """Someone who signed in on condorin.pe with a verified WhatsApp number."""

    id = models.AutoField(primary_key=True)
    phone = models.CharField('WhatsApp', max_length=15, unique=True, help_text='Solo dígitos con código de país.')
    consent_at = models.DateTimeField('aceptó los términos')
    last_sign_in_at = models.DateTimeField('último ingreso')
    created = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        db_table = 'accounts_member'
        ordering = ['-created']
        verbose_name = 'usuario de condorin.pe'
        verbose_name_plural = 'usuarios de condorin.pe'

    def __str__(self):
        return f'+{self.phone}'


class Admin(models.Model):
    """A Google account allowed into condorin.pe/admin. An active row is what grants access."""

    id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True, help_text='En minúsculas, como lo devuelve Google.')
    name = models.CharField(max_length=120, null=True, blank=True)
    active = models.BooleanField(default=True, db_default=True)
    # Nullable so Prisma, which never writes it, keeps inserting admins without it.
    phone = models.CharField(
        'WhatsApp', max_length=15, null=True, blank=True, validators=[phone_validator],
        help_text='Recibe por WhatsApp cada alerta reciente de todos los ríos. Vacío: no recibe alertas.',
    )
    created = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        db_table = 'accounts_admin'
        ordering = ['email']
        verbose_name = 'administrador'
        verbose_name_plural = 'administradores'

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)
