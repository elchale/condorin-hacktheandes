"""Object storage for `gs://` URIs and local paths / `file://` URIs (dev and tests).

Errors are typed so the HTTP layer can map them: `NotFound`/`PermanentError` (do not retry) and
`Transient` (retry). For local files the "generation" is the file's mtime in nanoseconds and custom
metadata is read from an optional `<file>.meta.json` sidecar (mimics GCS custom metadata).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOCAL_BUCKET = "local"


class StorageError(Exception):
    pass


class PermanentError(StorageError):
    """Will not succeed on retry (bad URI, forbidden, ...)."""


class NotFound(PermanentError):
    pass


class Transient(StorageError):
    """Retryable (5xx, throttling, network)."""


@dataclass(frozen=True)
class ParsedUri:
    scheme: str  # "gs" | "file"
    bucket: str
    obj: str
    path: Path | None = None  # local files only


@dataclass
class ObjectInfo:
    generation: str
    size: int
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_uri(uri: str) -> ParsedUri:
    if uri.startswith("gs://"):
        rest = uri[5:]
        bucket, _, obj = rest.partition("/")
        if not bucket:
            raise PermanentError(f"invalid gs:// URI: {uri!r}")
        return ParsedUri("gs", bucket, obj)
    if "://" in uri and not uri.startswith("file://"):
        raise PermanentError(f"unsupported URI scheme: {uri!r}")
    path = Path(uri[7:] if uri.startswith("file://") else uri).expanduser().resolve()
    return ParsedUri("file", LOCAL_BUCKET, str(path).lstrip("/"), path)


def join(prefix: str, *parts: str) -> str:
    return "/".join([prefix.rstrip("/"), *(p.strip("/") for p in parts)])


# --- GCS ----------------------------------------------------------------------------------------

_client = None


def _gcs():
    global _client
    if _client is None:
        from google.cloud import storage

        _client = storage.Client()
    return _client


def _map_gcs_error(err: Exception, uri: str) -> StorageError:
    from google.api_core import exceptions as gexc

    if isinstance(err, gexc.NotFound):
        return NotFound(uri)
    if isinstance(err, gexc.TooManyRequests | gexc.ServerError | gexc.RetryError):
        return Transient(f"{uri}: {err}")
    if isinstance(err, gexc.ClientError):  # 400/401/403/412...
        return PermanentError(f"{uri}: {err}")
    return Transient(f"{uri}: {err}")  # network errors, timeouts


def _gcs_call(uri: str, fn):
    try:
        return fn()
    except StorageError:
        raise
    except Exception as err:  # noqa: BLE001 - mapped to typed errors
        raise _map_gcs_error(err, uri) from err


# --- public API ---------------------------------------------------------------------------------


def stat(uri: str) -> ObjectInfo:
    p = parse_uri(uri)
    if p.scheme == "file":
        if not p.path.is_file():
            raise NotFound(uri)
        st = p.path.stat()
        side = p.path.with_name(p.path.name + ".meta.json")
        md = json.loads(side.read_text()) if side.is_file() else {}
        return ObjectInfo(str(st.st_mtime_ns), st.st_size, None, md)

    def _do():
        blob = _gcs().bucket(p.bucket).get_blob(p.obj)
        if blob is None:
            raise NotFound(uri)
        return ObjectInfo(str(blob.generation), blob.size, blob.content_type, blob.metadata or {})

    return _gcs_call(uri, _do)


def generation(uri: str) -> str:
    return stat(uri).generation


def read_bytes(uri: str, generation: str | None = None) -> bytes:
    """Read the whole object. With `generation`, GCS reads exactly that version (NotFound if gone)."""
    p = parse_uri(uri)
    if p.scheme == "file":
        try:
            return p.path.read_bytes()
        except FileNotFoundError as err:
            raise NotFound(uri) from err
        except IsADirectoryError as err:
            raise PermanentError(uri) from err

    def _do():
        blob = (
            _gcs().bucket(p.bucket).blob(p.obj, generation=int(generation) if generation else None)
        )
        return blob.download_as_bytes()

    return _gcs_call(uri, _do)


def write_bytes(uri: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    p = parse_uri(uri)
    if p.scheme == "file":
        p.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p.path)  # atomic: readers never see a partial result
        return
    _gcs_call(
        uri,
        lambda: _gcs().bucket(p.bucket).blob(p.obj).upload_from_string(data, content_type),
    )


def write_once(uri: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Create the object only if it does not exist yet and return its generation.

    An existing object is kept as is (its generation is returned), so evidence that the backend
    already pinned as `gs://bucket/obj#generation` is never replaced. Needs only
    `storage.objects.create` + `get` (objectCreator + objectViewer).
    """
    p = parse_uri(uri)
    if p.scheme == "file":
        if not p.path.is_file():
            write_bytes(uri, data, content_type)
        return str(p.path.stat().st_mtime_ns)

    def _do():
        from google.api_core import exceptions as gexc

        blob = _gcs().bucket(p.bucket).blob(p.obj)
        try:
            blob.upload_from_string(data, content_type, if_generation_match=0)
        except gexc.PreconditionFailed:
            existing = _gcs().bucket(p.bucket).get_blob(p.obj)
            if existing is None:  # deleted in between: let the caller retry
                raise Transient(f"{uri}: vanished after a precondition failure") from None
            return str(existing.generation)
        return str(blob.generation)

    return _gcs_call(uri, _do)


def write_json(uri: str, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode()
    write_bytes(uri, data, "application/json")


def read_json(uri: str) -> Any:
    return json.loads(read_bytes(uri))


def exists(uri: str) -> bool:
    p = parse_uri(uri)
    if p.scheme == "file":
        return p.path.is_file()
    return _gcs_call(uri, lambda: _gcs().bucket(p.bucket).blob(p.obj).exists())


def list_uris(prefix: str, limit: int | None = None) -> list[str]:
    """Objects under a prefix, sorted by name (sidecar `.meta.json` files excluded)."""
    p = parse_uri(prefix)
    if p.scheme == "file":
        if not p.path.is_dir():
            return []
        files = sorted(
            f for f in p.path.rglob("*") if f.is_file() and not f.name.endswith(".meta.json")
        )
        return [str(f) for f in files[:limit]]

    def _do():
        blobs = _gcs().list_blobs(p.bucket, prefix=p.obj, max_results=limit)
        return [f"gs://{p.bucket}/{b.name}" for b in blobs if not b.name.endswith("/")]

    return _gcs_call(prefix, _do)
