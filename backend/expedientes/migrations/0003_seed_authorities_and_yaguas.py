"""Seed the channels verified on official pages (October 2026) and the first river.

FEMA receives the criminal complaint (main route for illegal mining). OEFA's Servicio Nacional
de Denuncias Ambientales replaced SINADA on 29 May 2026 and forwards illegal mining to the
competent entity, leaving an administrative record. SERNANP is copied when the site is inside
a protected area. No authority email is seeded: none was confirmed, so nothing is emailed to
them until an admin fills one in.
"""
from django.db import migrations

AUTHORITIES = [
    {
        'code': 'fema',
        'name': 'Fiscalía Especializada en Materia Ambiental (Ministerio Público)',
        'kind': 'fiscalia',
        'is_primary': True,
        'submit_url': 'https://portal.mpfn.gob.pe/denuncias-en-linea',
        'phone': '0800 00 205 (gratuito)',
        'instructions': (
            'Entra a Denuncias en línea del Ministerio Público, resume los hechos y adjunta el PDF del expediente. '
            'Guarda el número de registro que te da el sistema. También puedes llevarlo impreso, firmado y con '
            'huella a la mesa de partes de la FEMA de tu región.'
        ),
        'order': 10,
    },
    {
        'code': 'oefa',
        'name': 'OEFA, Servicio Nacional de Denuncias Ambientales',
        'kind': 'oefa',
        'is_primary': True,
        'submit_url': 'https://sistemas.oefa.gob.pe/sifa/frontend/mf-registro-denuncias/#/bienvenida',
        'phone': '0800 10058 (gratuito)',
        'address': 'Oficina Loreto: Jr. Putumayo 342, Iquitos. Oficina Madre de Dios: Jr. Lambayeque 1365, Puerto Maldonado.',
        'instructions': (
            'Registra la denuncia en el formulario de OEFA y adjunta el PDF del expediente. OEFA la deriva a la '
            'entidad competente y te da un código para seguir su estado.'
        ),
        'order': 20,
    },
    {
        'code': 'sernanp',
        'name': 'SERNANP, jefatura del área natural protegida',
        'kind': 'sernanp',
        'is_primary': False,
        'instructions': (
            'Envía el PDF por la mesa de partes virtual del SERNANP dirigido a la jefatura del área protegida y pide '
            'su intervención inmediata. Los archivos pueden pesar hasta 30 MB.'
        ),
        'max_attachment_mb': 30,
        'order': 30,
    },
]

RIVERS = [
    {
        'slug': 'yaguas',
        'name': 'Yaguas',
        'basin': 'Putumayo',
        'district': 'Yaguas',
        'province': 'Putumayo',
        'region': 'Loreto',
        'protected_area': 'Parque Nacional Yaguas',
        'authorities': ['fema', 'oefa', 'sernanp'],
    },
]


def seed(apps, schema_editor):
    Authority = apps.get_model('expedientes', 'Authority')
    River = apps.get_model('ongs', 'River')
    for data in AUTHORITIES:
        Authority.objects.update_or_create(code=data['code'], defaults={k: v for k, v in data.items() if k != 'code'})
    for data in RIVERS:
        data = dict(data)
        codes = data.pop('authorities')
        river, _ = River.objects.update_or_create(slug=data.pop('slug'), defaults=data)
        river.authorities.set(Authority.objects.filter(code__in=codes))


class Migration(migrations.Migration):

    dependencies = [
        ('expedientes', '0002_initial'),
        ('ongs', '0001_initial'),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
