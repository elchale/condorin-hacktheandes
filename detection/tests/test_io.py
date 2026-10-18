from __future__ import annotations

import json

import pytest

from condorin.io import storage


def test_local_roundtrip(tmp_path):
    bucket = tmp_path / "bucket"
    uri = storage.join(str(bucket), "results", "v1", "abc.json")
    assert not storage.exists(uri)
    storage.write_json(uri, {"a": 1})
    assert storage.exists(uri)
    assert storage.read_json(uri) == {"a": 1}
    assert storage.read_json("file://" + uri) == {"a": 1}
    gen = storage.generation(uri)
    assert gen.isdigit()
    assert storage.list_uris(str(bucket)) == [uri]


def test_local_metadata_sidecar(tmp_path):
    img = tmp_path / "yaguas" / "a.jpg"
    img.parent.mkdir()
    img.write_bytes(b"x")
    (tmp_path / "yaguas" / "a.jpg.meta.json").write_text(json.dumps({"satellite": "Skyfi"}))
    assert storage.stat(str(img)).metadata == {"satellite": "Skyfi"}
    assert storage.list_uris(str(tmp_path)) == [str(img)]


def test_not_found_is_permanent(tmp_path):
    missing = str(tmp_path / "nope.jpg")
    with pytest.raises(storage.NotFound):
        storage.read_bytes(missing)
    with pytest.raises(storage.PermanentError):
        storage.stat(missing)
    assert issubclass(storage.NotFound, storage.PermanentError)
    assert not issubclass(storage.Transient, storage.PermanentError)


def test_parse_uri():
    p = storage.parse_uri("gs://river-images/yaguas/a.jpeg")
    assert (p.scheme, p.bucket, p.obj) == ("gs", "river-images", "yaguas/a.jpeg")
    assert storage.parse_uri("/tmp/x.jpg").bucket == storage.LOCAL_BUCKET
    with pytest.raises(storage.PermanentError):
        storage.parse_uri("s3://bucket/x")


def test_gcs_error_mapping():
    from google.api_core import exceptions as gexc

    assert isinstance(storage._map_gcs_error(gexc.NotFound("x"), "u"), storage.NotFound)
    assert isinstance(storage._map_gcs_error(gexc.Forbidden("x"), "u"), storage.PermanentError)
    assert isinstance(storage._map_gcs_error(gexc.ServiceUnavailable("x"), "u"), storage.Transient)
    assert isinstance(storage._map_gcs_error(gexc.TooManyRequests("x"), "u"), storage.Transient)
    assert isinstance(storage._map_gcs_error(ConnectionError("x"), "u"), storage.Transient)
