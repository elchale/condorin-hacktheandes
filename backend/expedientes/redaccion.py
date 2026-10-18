"""Redacción asistida con Claude (LangChain) para los hechos del expediente.

Está detrás de la bandera EXPEDIENTE_IA_ENABLED (apagada por defecto). Con la bandera apagada, o sin
ANTHROPIC_API_KEY, o si la llamada falla, el expediente conserva el borrador determinista de
`drafting.draft_facts`, así la apertura nunca depende de un servicio externo.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM = (
    'Eres el asistente legal de Ojo de Cóndor, un sistema que detecta dragas de minería ilegal en ríos '
    'de la Amazonía peruana con imágenes satelitales y ayuda a ONGs a presentar denuncias ante la Fiscalía '
    '(FEMA) y OEFA. Recibirás un borrador de la sección "Hechos" de una denuncia, escrito a partir de los '
    'datos de una detección. Devuelve una versión mejorada de esa sección, en español formal del Perú, '
    'siguiendo el estilo del artículo 328 del Nuevo Código Procesal Penal: párrafos numerados, claros y '
    'verificables. Reglas: no inventes datos, fechas, coordenadas, nombres ni normas que no estén en el '
    'borrador; conserva todos los números, coordenadas y fechas exactamente como vienen; no uses guiones '
    'como signo de puntuación; responde solo con el texto de los hechos, sin título ni comentarios.'
)


def enabled() -> bool:
    return bool(getattr(settings, 'EXPEDIENTE_IA_ENABLED', False) and getattr(settings, 'ANTHROPIC_API_KEY', ''))


def _model():
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.EXPEDIENTE_IA_MODEL,
        api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=settings.EXPEDIENTE_IA_MAX_TOKENS,
        timeout=settings.EXPEDIENTE_IA_TIMEOUT,
        max_retries=1,
        # Opus 5.5 defaults to medium; set it so a model change never silently raises the spend.
        effort='medium',
    )


def improve_facts(draft: str, place: str) -> str:
    """The facts Claude writes from the deterministic draft; the draft itself when the flag is off or it fails."""
    if not enabled() or not draft.strip():
        return draft
    try:
        response = _model().invoke([
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': f'Lugar: {place}\n\nBorrador de los hechos:\n\n{draft}'},
        ])
        text = (response.text or '').strip()
    except Exception:
        logger.exception('expediente IA: Claude failed, keeping the deterministic draft')
        return draft
    if not text:
        logger.warning('expediente IA: empty answer, keeping the deterministic draft')
        return draft
    return text
