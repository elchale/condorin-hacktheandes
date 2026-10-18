"""Access to Cloud Storage: pin evidence versions, hash crops, sign links, archive the final PDFs."""
import base64
import json
import logging
from datetime import timedelta
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

# Crops are small PNGs; anything bigger is not a crop and is not downloaded.
MAX_CROP_BYTES = 10 * 1024 * 1024


class StorageUnavailable(Exception):
    pass


def parse_gs_uri(uri: str) -> tuple[str, str, str | None]:
    """'gs://bucket/path/file.png#123' → ('bucket', 'path/file.png', '123')."""
    if not uri.startswith('gs://'):
        raise ValueError(f'Not a gs:// URI: {uri}')
    rest, _, generation = uri[5:].partition('#')
    bucket, _, name = rest.partition('/')
    if not bucket or not name:
        raise ValueError(f'Not a gs:// URI: {uri}')
    return bucket, name, generation or None


@lru_cache(maxsize=1)
def _client():
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover
        raise StorageUnavailable(str(exc)) from exc

    try:
        if settings.GCS_CREDENTIALS_JSON:
            info = json.loads(base64.b64decode(settings.GCS_CREDENTIALS_JSON))
            credentials = service_account.Credentials.from_service_account_info(info)
            return storage.Client(project=settings.GCS_PROJECT_ID or info.get('project_id'), credentials=credentials)
        return storage.Client(project=settings.GCS_PROJECT_ID or None)
    except Exception as exc:
        raise StorageUnavailable(str(exc)) from exc


def _blob(bucket: str, name: str, generation: str | None = None):
    return _client().bucket(bucket).blob(name, generation=int(generation) if generation else None)


def object_metadata(bucket: str, name: str, generation: str | None = None) -> dict:
    """Hashes and size as GCS stores them (md5 is base64, as in the GCS API)."""
    try:
        blob = _blob(bucket, name, generation)
        blob.reload()
    except StorageUnavailable:
        raise
    except Exception as exc:
        raise StorageUnavailable(str(exc)) from exc
    return {
        'generation': str(blob.generation),
        'md5_hash': blob.md5_hash or '',
        'crc32c': blob.crc32c or '',
        'size_bytes': blob.size,
    }


def download(bucket: str, name: str, generation: str | None = None) -> tuple[bytes, str]:
    """Bytes of a small object and the generation that was actually read."""
    try:
        blob = _blob(bucket, name, generation)
        blob.reload()
        if blob.size and blob.size > MAX_CROP_BYTES:
            raise StorageUnavailable(f'{name} is {blob.size} bytes, too large to download')
        return blob.download_as_bytes(), str(blob.generation)
    except StorageUnavailable:
        raise
    except Exception as exc:
        raise StorageUnavailable(str(exc)) from exc


def upload(bucket: str, name: str, content: bytes, content_type: str) -> str:
    """Creates the object (never overwrites one) and returns its generation."""
    try:
        blob = _blob(bucket, name)
        blob.upload_from_string(content, content_type=content_type, if_generation_match=0)
        return str(blob.generation)
    except StorageUnavailable:
        raise
    except Exception as exc:
        raise StorageUnavailable(str(exc)) from exc


def signed_url(bucket: str, name: str, generation: str | None = None,
               minutes: int | None = None, download_as: str | None = None) -> str | None:
    """A V4 signed GET link to that exact version, or None when signing is not possible."""
    minutes = minutes or settings.GCS_SIGNED_URL_MINUTES
    params = {}
    if download_as:
        params['response_disposition'] = f'attachment; filename="{download_as}"'
    try:
        return _blob(bucket, name, generation).generate_signed_url(
            version='v4', expiration=timedelta(minutes=minutes), method='GET', **params,
        )
    except Exception as exc:
        logger.warning('could not sign gs://%s/%s: %s', bucket, name, exc)
        return None
