"""The denuncia as a PDF: escrito plus annexes with the satellite evidence and its hashes.

Structure follows what the Fiscalía and OEFA ask for (NCPP art. 328, DAR's 2025 guide):
denunciante, hechos, ubicación, presuntos responsables, fundamentos, medios probatorios,
petitorio and signature. Drafts carry a BORRADOR watermark and no folio.
"""
import io
import logging
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from PIL import ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import clock, gcs
from core.geo import coord, maps_url, utm
from detections.text import fecha_corta, fecha_larga

from .drafting import earlier_sightings, place_sentence

logger = logging.getLogger(__name__)

MARCA_HEX = '#e11d2e'
MARCA = colors.HexColor(MARCA_HEX)
GRIS = colors.HexColor('#52525b')
BORDE = colors.HexColor('#e3e3e8')

_base = getSampleStyleSheet()
S = {
    'title': ParagraphStyle('title', parent=_base['Title'], fontSize=14, leading=18, spaceAfter=4),
    'sumilla': ParagraphStyle('sumilla', parent=_base['Normal'], alignment=TA_CENTER, textColor=GRIS, spaceAfter=12),
    'h': ParagraphStyle('h', parent=_base['Heading2'], fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=6),
    'p': ParagraphStyle('p', parent=_base['Normal'], fontSize=10, leading=14.5, spaceAfter=6),
    'small': ParagraphStyle('small', parent=_base['Normal'], fontSize=8, leading=11, textColor=GRIS),
    'cell': ParagraphStyle('cell', parent=_base['Normal'], fontSize=8.5, leading=11),
}


def _p(text: str, style='p') -> Paragraph:
    return Paragraph(escape(text).replace('\n', '<br/>'), S[style])


def _paragraphs(text: str) -> list:
    return [_p(block) for block in text.strip().split('\n\n') if block.strip()]


def _table(rows: list[list], widths: list[float]) -> Table:
    data = [[c if not isinstance(c, str) else Paragraph(escape(c), S['cell']) for c in row] for row in rows]
    table = Table(data, colWidths=widths, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f3f6')),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    return table


def _flowable(content: bytes, side: float) -> Image:
    img = Image(io.BytesIO(content))
    scale = min(side / img.imageWidth, side / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
    return img


def _png(picture) -> bytes:
    out = io.BytesIO()
    picture.save(out, format='PNG')
    return out.getvalue()


def _scene_picture(image):
    """The scene as a Pillow image, read at its pinned version; None when the bucket is unreachable."""
    try:
        content, _ = gcs.download(image.bucket, image.object_name, image.generation)
        return PILImage.open(io.BytesIO(content)).convert('RGB')
    except (gcs.StorageUnavailable, OSError) as exc:
        logger.warning('pdf: scene %s unavailable: %s', image.gs_uri, exc)
        return None


def _box(detection) -> tuple[int, int, int, int]:
    x, y, w, h = detection.bbox
    return x, y, x + w, y + h


def _scene_with_boxes(scene, detections):
    picture = scene.copy()
    draw = ImageDraw.Draw(picture)
    width = max(2, picture.width // 400)
    for i, d in enumerate(detections, start=1):
        x0, y0, x1, y1 = _box(d)
        pad = width * 3
        draw.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], outline=MARCA_HEX, width=width)
        draw.text((x1 + pad + 4, y0 - pad), str(i), fill='#ffffff', stroke_width=2, stroke_fill='#000000',
                  font_size=max(14, picture.width // 50))
    return _flowable(_png(picture), 14 * cm)


def _crop_image(detection, scene):
    """The detection's crop: its own file when the detector made one, else cut from the scene around the box."""
    if detection.crop_uri:
        try:
            bucket, name, generation = gcs.parse_gs_uri(detection.crop_uri)
        except ValueError as exc:
            logger.warning('pdf: crop %s unavailable: %s', detection.crop_uri, exc)
            return None
        image = detection.image
        if (bucket, name) != (image.bucket, image.object_name):
            try:
                content, _ = gcs.download(bucket, name, detection.crop_generation or generation)
            except gcs.StorageUnavailable as exc:
                logger.warning('pdf: crop %s unavailable: %s', detection.crop_uri, exc)
                return None
            return _flowable(content, 7 * cm)
    if scene is None:
        return None
    x0, y0, x1, y1 = _box(detection)
    half = max(80, 4 * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    picture = scene.crop((cx - half, cy - half, cx + half, cy + half))
    pad = max(2, half // 40)
    ImageDraw.Draw(picture).rectangle(
        [x0 - (cx - half) - pad, y0 - (cy - half) - pad, x1 - (cx - half) + pad, y1 - (cy - half) + pad],
        outline=MARCA_HEX, width=max(2, half // 60))
    return _flowable(_png(picture), 7 * cm)


def _copernicus_credit(image) -> str:
    if image.satellite.lower().startswith('sentinel'):
        return f'Contiene datos modificados de Copernicus Sentinel {image.captured_at:%Y}.'
    return ''


def build_pdf(expediente, final: bool) -> bytes:
    image = expediente.image
    river = image.river
    detections = list(image.alerting_detections())
    authorities = list(expediente.authorities.filter(active=True))
    history = earlier_sightings(image)
    today = clock.today()

    story = [
        _p('DENUNCIA POR PRESUNTO DELITO DE MINERÍA ILEGAL', 'title'),
        _p(f'Sumilla: Denuncia minería ilegal con dragas en el río {river.name}. '
           'Solicita constatación fiscal e interdicción.', 'sumilla'),
        _p('Señores: ' + '; '.join(a.name for a in authorities) + '.'),
    ]

    # I. Denunciante
    story.append(_p('I. Datos del denunciante', 'h'))
    rep = f'{expediente.rep_name}, con DNI {expediente.rep_dni or "pendiente"}'
    if expediente.rep_position:
        rep += f', en calidad de {expediente.rep_position}'
    story.append(_p(
        f'{expediente.ong_name}' + (f', con RUC {expediente.ong_ruc}' if expediente.ong_ruc else '')
        + f', con domicilio en {expediente.ong_address or "pendiente"}, debidamente representada por {rep}, '
        f'señalando como correo para notificaciones {expediente.notify_email or "pendiente"}, '
        'ante ustedes nos presentamos y decimos:'
    ))

    # II. Hechos
    story.append(_p('II. Hechos', 'h'))
    story += _paragraphs(expediente.facts)
    if expediente.field_observations.strip():
        story.append(_p('Observaciones en campo:'))
        story += _paragraphs(expediente.field_observations)
    if expediente.risk_notes.strip():
        story.append(_p('Riesgos para la comunidad:'))
        story += _paragraphs(expediente.risk_notes)

    # III. Ubicación
    story.append(_p('III. Ubicación', 'h'))
    story.append(_p(f'Los hechos ocurren en el {place_sentence(river)}.'
                    + (f' Referencia: {expediente.place_reference}.' if expediente.place_reference else '')))
    rows = [['N.°', 'Latitud, longitud (WGS84)', 'UTM (WGS84)', 'Confianza', 'Mapa']]
    for i, d in enumerate(detections, start=1):
        u = utm(float(d.lat), float(d.lon))
        rows.append([str(i), f'{coord(d.lat)}, {coord(d.lon)}', u['label'], f'{d.confidence:.0%}',
                     maps_url(coord(d.lat), coord(d.lon))])
    story.append(_table(rows, [1 * cm, 3.6 * cm, 4.2 * cm, 1.8 * cm, 6.4 * cm]))

    # IV. Presuntos responsables
    story.append(_p('IV. Presuntos responsables', 'h'))
    story += _paragraphs(expediente.suspects or 'Por identificar.')

    # V. Fundamentos
    story.append(_p('V. Fundamentos de derecho', 'h'))
    story += _paragraphs(
        'Artículos 307-A y 307-B del Código Penal, que tipifican el delito de minería ilegal y sus agravantes.\n\n'
        'Decreto Legislativo 1100, que prohíbe el uso de dragas y artefactos similares en los ríos y '
        'regula la interdicción de la minería ilegal.\n\n'
        'Artículos 326 y 328 del Código Procesal Penal, sobre la facultad de denunciar y el contenido de la denuncia.'
        + ('\n\nLey 26834, Ley de Áreas Naturales Protegidas, por encontrarse los hechos dentro del '
           f'{river.protected_area}.' if river.protected_area else '')
    )

    # VI. Medios probatorios
    story.append(_p('VI. Medios probatorios', 'h'))
    annexes = [
        'Anexo 1: Ficha de las detecciones satelitales con coordenadas (sección III).',
        'Anexo 2: Recortes de la imagen satelital de cada detección, con su código de integridad SHA-256.',
        'Anexo 3: Datos de la imagen satelital original y de su custodia.',
    ]
    if history:
        annexes.append('Anexo 4: Detecciones anteriores en la misma zona.')
    if expediente.field_evidence_links.strip():
        annexes.append(f'Anexo {len(annexes) + 1}: Fotos y videos tomados en campo.')
    story += [_p(a) for a in annexes]

    # VII. Petitorio
    story.append(_p('VII. Petitorio', 'h'))
    petitorio = [
        'Se disponga la constatación fiscal en el lugar de los hechos a la brevedad posible.',
        'Se ejecuten las acciones de interdicción previstas en el Decreto Legislativo 1100.',
        'Se coordine con la Capitanía de Puerto (DICAPI) y la Policía Nacional del Perú'
        + (', así como con la jefatura del ' + river.protected_area if river.protected_area else '') + '.',
        'Se ordene la preservación de la evidencia satelital adjunta y de la que obtengan las entidades competentes.',
    ]
    story += [_p(f'{i}. {t}') for i, t in enumerate(petitorio, start=1)]
    if expediente.identity_reserved:
        story.append(_p('Otrosí: Solicitamos la reserva de identidad de las personas que aportan información, '
                        'en atención al riesgo que corren en la zona.'))

    story.append(Spacer(1, 1.6 * cm))
    story.append(KeepTogether([
        _p(f'{place_city(river)}, {fecha_corta(clock.now()) if final else "fecha de presentación"}'),
        Spacer(1, 2 * cm),
        _p('______________________________'),
        _p(f'{expediente.rep_name}\nDNI {expediente.rep_dni or "pendiente"}'
           + (f'\n{expediente.rep_position}' if expediente.rep_position else '') + f'\n{expediente.ong_name}'),
        _p('Firma y huella digital', 'small'),
    ]))

    # Annex 2 and 3
    scene = _scene_picture(image)
    story.append(_p('Anexo 2: Recortes de la imagen satelital', 'h'))
    for i, d in enumerate(detections, start=1):
        img = _crop_image(d, scene)
        caption = (f'Detección {i}: {coord(d.lat)}, {coord(d.lon)}, confianza {d.confidence:.0%}. '
                   f'Archivo {d.crop_uri or "sin recorte"}'
                   + (f'#{d.crop_generation}' if d.crop_generation and '#' not in d.crop_uri else '')
                   + (f'. SHA-256 {d.crop_sha256}.' if d.crop_sha256 else '.'))
        story.append(KeepTogether(([img] if img else []) + [_p(caption, 'small'), Spacer(1, 6)]))

    story.append(_p('Anexo 3: Imagen satelital original y custodia', 'h'))
    if scene is not None:
        story.append(KeepTogether([
            _scene_with_boxes(scene, detections),
            _p('Imagen completa; cada recuadro numerado corresponde a una detección de la sección III.', 'small'),
            Spacer(1, 6),
        ]))
    story.append(_table([
        ['Dato', 'Valor'],
        ['Satélite', image.satellite],
        ['Fecha de captura', f'{fecha_larga(image.captured_at)} (hora de Perú), {image.captured_at:%Y-%m-%dT%H:%MZ} UTC'],
        ['Archivo', image.gs_uri],
        ['MD5 (Google Cloud Storage)', image.md5_hash or 'no disponible'],
        ['CRC32C (Google Cloud Storage)', image.crc32c or 'no disponible'],
        ['Tamaño', f'{image.size_bytes:,} bytes' if image.size_bytes else 'no disponible'],
        ['Detección', f'{image.model_name} {image.model_version}, recibida el {fecha_larga(image.created)}'],
    ], [5 * cm, 12 * cm]))
    story.append(Spacer(1, 4))
    story.append(_p('El número después de # es la versión inmutable del archivo en el almacenamiento: '
                    'cualquier modificación crearía una versión distinta con otro código de integridad. '
                    + _copernicus_credit(image), 'small'))

    if history:
        story.append(_p('Anexo 4: Detecciones anteriores en la misma zona', 'h'))
        rows = [['Fecha', 'Satélite', 'Detecciones', 'Archivo']]
        rows += [[fecha_corta(h.captured_at), h.satellite, str(h.alerting_detections().count()), h.gs_uri]
                 for h in history]
        story.append(_table(rows, [3.2 * cm, 2.8 * cm, 2.2 * cm, 8.8 * cm]))

    if expediente.field_evidence_links.strip():
        story.append(_p(f'Anexo {len(annexes)}: Fotos y videos tomados en campo', 'h'))
        story += _paragraphs(expediente.field_evidence_links)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f'Denuncia {expediente.folio or "borrador"}', author=expediente.ong_name)
    label = expediente.folio if final else 'BORRADOR'
    doc.build(story, onFirstPage=_decorate(label, final, today), onLaterPages=_decorate(label, final, today))
    return buffer.getvalue()


def place_city(river) -> str:
    return river.province or river.region or 'Lima'


def _decorate(label: str, final: bool, today):
    def draw(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(MARCA)
        canvas.drawString(2 * cm, height - 1.2 * cm, 'Ojo de Cóndor')
        canvas.setFillColor(GRIS)
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(width - 2 * cm, height - 1.2 * cm, label)
        canvas.drawString(2 * cm, 1.1 * cm, f'Generado por Ojo de Cóndor el {today:%d/%m/%Y}')
        canvas.drawRightString(width - 2 * cm, 1.1 * cm, f'Página {doc.page}')
        if not final:
            canvas.setFont('Helvetica-Bold', 70)
            canvas.setFillColor(colors.Color(0.88, 0.11, 0.18, alpha=0.08))
            canvas.translate(width / 2, height / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, 'BORRADOR')
        canvas.restoreState()
    return draw
