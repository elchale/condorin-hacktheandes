"""Bounded HTTP for the open data feeds: strict timeouts, a size cap and one User-Agent."""
import logging
import time
from collections.abc import Iterator

import requests

logger = logging.getLogger(__name__)

USER_AGENT = 'OjoDeCondor/1.0 (+https://condorin.pe)'
TIMEOUT = (5, 15)  # connect, read (between bytes)
DEFAULT_MAX_BYTES = 5 * 1024 * 1024


class TooLarge(Exception):
    pass


class Meter:
    """Counts the bytes a fetch pulled, across several calls."""

    def __init__(self):
        self.bytes = 0


def _session() -> requests.Session:
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT
    return session


def get_bytes(url: str, params=None, *, max_bytes: int = DEFAULT_MAX_BYTES, meter: Meter | None = None,
              timeout=TIMEOUT) -> bytes:
    """GET a whole body, refusing anything bigger than max_bytes."""
    started = time.monotonic()
    with _session().get(url, params=params, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise TooLarge(f'{url} is over {max_bytes} bytes')
            chunks.append(chunk)
    if meter is not None:
        meter.bytes += size
    logger.info('fuentes: GET %s %s bytes in %d ms', url.split('?')[0], size, (time.monotonic() - started) * 1000)
    return b''.join(chunks)


def get_json(url: str, params=None, **kwargs):
    import json
    return json.loads(get_bytes(url, params, **kwargs))


def stream_lines(url: str, *, max_bytes: int, meter: Meter | None = None, timeout=TIMEOUT) -> Iterator[str]:
    """Yield the decoded lines of a text body; stops quietly (with a warning) at max_bytes."""
    started, size = time.monotonic(), 0
    try:
        with _session().get(url, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(chunk_size=64 * 1024):
                size += len(line) + 1
                if size > max_bytes:
                    logger.warning('fuentes: %s cut at %s bytes', url, max_bytes)
                    break
                yield line.decode('utf-8', 'replace')
    finally:
        if meter is not None:
            meter.bytes += size
        logger.info('fuentes: GET %s %s bytes in %d ms', url, size, (time.monotonic() - started) * 1000)
