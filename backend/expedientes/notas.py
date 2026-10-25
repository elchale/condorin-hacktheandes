"""A member's field notes ("notas de campo"), kept in Atomic Memory and offered again on their next expediente.

A member writes a short note they reviewed themselves (how to reach the place, who to call in the community,
what the authority asked for last time) and saves it on purpose. When they open another expediente, the notes
that best match the river come back beside the form; they can copy one into the observaciones, correct it or
delete it. The notes are reference for the person only: they never change a detection, an alert, the hechos
or the evidence, and nothing reaches the denuncia unless the member copies it there.

Off by default (ATOMIC_MEMORY_ENABLED and ATOMIC_MEMORY_API_KEY). The key stays on the server. Each member row
is one memory subject (`user_id`), derived here from the member behind a WhatsApp code session, never from the
request; no `session_id` is sent, because on Atomic Memory Cloud it would replace that subject.

HTTP contract (docs.atomicstrata.ai, api-reference/http): POST /v1/memories/ingest/quick with
skip_extraction (stored verbatim with our metadata), POST /v1/memories/search/fast, GET and DELETE
/v1/memories/{id}, all with `Authorization: Bearer <key>`.

Every answer is distrusted: the base URL must be https (plain http only to a loopback fixture), redirects are
never followed, a body is read up to MAX_RESPONSE_BYTES within a total deadline, and a write or a delete only
counts when the documented confirmation comes back (`stored_memory_ids`, `success: true`). Anything else is
MemoryUnavailable, so the page never says a note was saved or deleted when it was not.
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SOURCE_SITE = 'condorin-notas-de-campo'
MAX_CHARS = 500
SEARCH_LIMIT = 5
# A single memory row carries its embedding (a 3072 float vector is about 60 KB of JSON), so not 64 KiB.
MAX_RESPONSE_BYTES = 256 * 1024
# ATOMIC_MEMORY_TIMEOUT is clamped to this range: never unbounded, never so short every call fails.
MIN_TIMEOUT, MAX_TIMEOUT = 0.1, 10.0
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


class MemoryUnavailable(Exception):
    """Atomic Memory did not answer, answered an error or something malformed, or did not confirm the write."""


class NoteNotFound(Exception):
    """No note with that id for this member."""


class InvalidNote(ValueError):
    """The note text is not a string, is empty, or is longer than MAX_CHARS. Nothing is cut silently."""


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    river: str
    river_name: str
    created_at: str

    def as_dict(self) -> dict:
        return {'id': self.id, 'text': self.text, 'river': self.river, 'river_name': self.river_name,
                'created_at': self.created_at}


def enabled() -> bool:
    return bool(settings.ATOMIC_MEMORY_ENABLED and settings.ATOMIC_MEMORY_API_KEY and settings.ATOMIC_MEMORY_API_URL)


def subject(member) -> str:
    """The memory subject of one member row (one person in one ONG). No phone or name leaves the server."""
    return f'{settings.ATOMIC_MEMORY_SUBJECT_PREFIX}:member:{member.pk}'


def valid_text(text) -> str:
    """The note as the member wrote it (only the ends trimmed). Raises InvalidNote instead of altering it."""
    if not isinstance(text, str):
        raise InvalidNote('La nota debe ser texto.')
    text = text.strip()
    if not text:
        raise InvalidNote('Escribe la nota.')
    if len(text) > MAX_CHARS:
        raise InvalidNote(f'La nota puede tener hasta {MAX_CHARS} caracteres.')
    return text


def base_url(raw: str) -> str:
    """The provider base URL: https, or plain http only to a loopback host (the local fixture)."""
    parts = urlsplit(str(raw or '').strip())
    host = (parts.hostname or '').lower()
    ok = bool(host) and not parts.username and not parts.password and not parts.query and not parts.fragment and (
        parts.scheme == 'https' or (parts.scheme == 'http' and host in LOOPBACK))
    if not ok:
        raise MemoryUnavailable('ATOMIC_MEMORY_API_URL must be https (http only for a loopback fixture)')
    return f'{parts.scheme}://{parts.netloc}{parts.path.rstrip("/")}'


def timeout() -> float:
    try:
        value = float(settings.ATOMIC_MEMORY_TIMEOUT)
    except (TypeError, ValueError):
        value = MAX_TIMEOUT
    if value != value:  # NaN
        value = MAX_TIMEOUT
    return min(max(value, MIN_TIMEOUT), MAX_TIMEOUT)


def _read(response, deadline: float) -> bytes:
    declared = response.headers.get('Content-Length')
    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise MemoryUnavailable('response too large')
    body = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise MemoryUnavailable('response too large')
        if time.monotonic() > deadline:
            raise MemoryUnavailable('response too slow')
    return bytes(body)


def _call(method: str, path: str, *, params: dict | None = None, body: dict | None = None,
          one_memory: bool = False) -> dict:
    """The JSON object Atomic Memory answered. A 404 is NoteNotFound only on a single memory route; any other
    non 2xx status (redirects included, they are never followed), a body over the limit, a slow body or one
    that is not a JSON object is MemoryUnavailable."""
    try:
        url = base_url(settings.ATOMIC_MEMORY_API_URL) + path
    except MemoryUnavailable:
        logger.error('atomic memory: ATOMIC_MEMORY_API_URL is not https (or http to a loopback host)')
        raise
    limit = timeout()
    deadline = time.monotonic() + limit
    try:
        with requests.Session() as http, http.request(
            method, url, params=params, json=body, timeout=limit, allow_redirects=False, stream=True,
            headers={'Authorization': f'Bearer {settings.ATOMIC_MEMORY_API_KEY}', 'Accept': 'application/json'},
        ) as response:
            status_code = response.status_code
            raw = _read(response, deadline) if 200 <= status_code < 300 else b''
    except requests.RequestException as exc:
        logger.warning('atomic memory: %s %s failed: %s', method, path, type(exc).__name__)
        raise MemoryUnavailable() from exc
    except MemoryUnavailable:
        logger.warning('atomic memory: %s %s answered a body over the size or time limit', method, path)
        raise
    if status_code == 404 and one_memory:
        raise NoteNotFound()
    if not 200 <= status_code < 300:
        logger.warning('atomic memory: %s %s answered %s', method, path, status_code)
        raise MemoryUnavailable()
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning('atomic memory: %s %s answered something that is not JSON', method, path)
        raise MemoryUnavailable() from exc
    if not isinstance(data, dict):
        logger.warning('atomic memory: %s %s answered JSON that is not an object', method, path)
        raise MemoryUnavailable()
    return data


def _uuid(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _note(row: dict) -> Note | None:
    """One of our notes from a memory row; None for rows this app did not write or whose fields are malformed."""
    meta = row.get('metadata')
    if not isinstance(meta, dict) or meta.get('condorin_kind') != 'nota_de_campo':
        return None
    note_id, text = _uuid(row.get('id')), meta.get('condorin_text')
    river, river_name = meta.get('condorin_river'), meta.get('condorin_river_name', '')
    created_at = row.get('created_at') or ''
    if (note_id is None or not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS
            or not isinstance(river, str) or not isinstance(river_name, str) or not isinstance(created_at, str)):
        logger.warning('atomic memory: skipped a malformed field note')
        return None
    return Note(id=note_id, text=text, river=river, river_name=river_name, created_at=created_at)


def _memory_id(note_id) -> str:
    """Atomic Memory ids are UUIDs; anything else never reaches the URL."""
    memory_id = _uuid(note_id)
    if memory_id is None:
        raise NoteNotFound()
    return memory_id


def relevant(member, river, place: str = '') -> list[Note]:
    """The member's notes that best match this river, the river's own first."""
    query = f'Notas de campo sobre el río {river.name} {river.region} {place}'.strip()
    data = _call('POST', '/v1/memories/search/fast', body={
        'user_id': subject(member), 'query': query, 'limit': SEARCH_LIMIT, 'source_site': SOURCE_SITE,
    })
    rows = data.get('memories')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        logger.warning('atomic memory: search answered without a list of memories')
        raise MemoryUnavailable()
    notes = [n for n in (_note(row) for row in rows) if n]
    return sorted(notes, key=lambda n: n.river != river.slug)


def save(member, river, text: str, expediente_id: int | None = None) -> Note:
    """Stores one note verbatim. Raises MemoryUnavailable unless Atomic Memory returns the id it stored."""
    text = valid_text(text)
    data = _call('POST', '/v1/memories/ingest/quick', body={
        'user_id': subject(member),
        'conversation': f'Nota de campo sobre el río {river.name}: {text}',
        'source_site': SOURCE_SITE,
        'skip_extraction': True,
        'content_class': 'summary',
        'metadata': {
            'condorin_kind': 'nota_de_campo', 'condorin_text': text, 'condorin_river': river.slug,
            'condorin_river_name': river.name, 'condorin_expediente': expediente_id,
        },
    })
    ids = data.get('stored_memory_ids')
    if not isinstance(ids, list) or len(ids) != 1 or _uuid(ids[0]) is None:
        logger.warning('atomic memory: ingest did not return exactly one valid stored id')
        raise MemoryUnavailable()
    return Note(id=_uuid(ids[0]), text=text, river=river.slug, river_name=river.name, created_at='')


def get(member, note_id) -> Note:
    data = _call('GET', f'/v1/memories/{_memory_id(note_id)}', params={'user_id': subject(member)}, one_memory=True)
    note = _note(data)
    if note is None:
        raise NoteNotFound()
    return note


def delete(member, note_id) -> None:
    """Deletes one note. Only the documented `{"success": true}` counts; anything else is MemoryUnavailable."""
    data = _call('DELETE', f'/v1/memories/{_memory_id(note_id)}', params={'user_id': subject(member)},
                 one_memory=True)
    if data.get('success') is not True:
        logger.warning('atomic memory: delete was not confirmed')
        raise MemoryUnavailable()


def correct(member, note_id, text: str) -> tuple[Note, bool]:
    """Saves the corrected note, then deletes the old one. Returns (new note, whether the old one is gone), so
    the page never says the old text was removed when it was not. The note keeps its river."""
    from ongs.models import River

    text = valid_text(text)
    old = get(member, note_id)
    river = River.objects.filter(slug=old.river).first()
    if river is None:
        raise NoteNotFound()
    new = save(member, river, text)
    try:
        delete(member, old.id)
    except (MemoryUnavailable, NoteNotFound):
        logger.warning('atomic memory: corrected note saved but the old one was not deleted')
        return new, False
    return new, True


# The same guarded HTTP call, for the ONG memory (expedientes/memoria.py).
call = _call
