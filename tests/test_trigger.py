from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from condorin.trigger import app as trigger


@pytest.fixture
def client(monkeypatch):
    calls = {"run": [], "check": []}

    def fake_check(bucket, prefix):
        calls["check"].append((bucket, prefix))
        return prefix != "yaguas/1999-01-01"

    def fake_run(settings, prefix):
        calls["run"].append((settings.job_path, prefix))
        return {
            "name": "projects/p/locations/us-central1/operations/op-1",
            "metadata": {
                "name": "projects/p/locations/us-central1/jobs/condorin-detector/executions/condorin-detector-abc"
            },
        }

    monkeypatch.setattr(trigger, "prefix_has_objects", fake_check)
    monkeypatch.setattr(trigger, "run_job", fake_run)
    return TestClient(trigger.app), calls


def test_procesar_starts_job_with_prefix(client):
    c, calls = client
    r = c.post("/procesar", json={"prefix": "yaguas/2026-10-18"})
    assert r.status_code == 202
    assert r.json()["execution"].endswith("/executions/condorin-detector-abc")
    assert r.json()["prefix"] == "yaguas/2026-10-18"
    path, prefix = calls["run"][0]
    assert path == "projects/wisecai-consultor-prod/locations/us-central1/jobs/condorin-detector"
    assert prefix == "yaguas/2026-10-18"


def test_procesar_accepts_full_gs_uri(client):
    c, calls = client
    r = c.post("/procesar", json={"prefix": "gs://river-images/yaguas/2026-10-18T0645Z_s1.jpeg"})
    assert r.status_code == 202 and calls["run"][0][1] == "yaguas/2026-10-18T0645Z_s1.jpeg"


@pytest.mark.parametrize(
    "prefix",
    ["", "../etc", "yaguas/../x", "crops/yaguas", "Yaguas/2026", "yaguas/a b", "gs://other/yaguas"],
)
def test_procesar_rejects_bad_prefixes(client, prefix):
    c, calls = client
    assert c.post("/procesar", json={"prefix": prefix}).status_code == 422
    assert calls["run"] == []


def test_procesar_404_on_empty_prefix(client):
    c, calls = client
    assert c.post("/procesar", json={"prefix": "yaguas/1999-01-01"}).status_code == 404
    assert calls["run"] == []


def test_procesar_502_when_job_cannot_start(client, monkeypatch):
    c, _ = client

    def boom(settings, prefix):
        raise RuntimeError("Cloud Run API answered 403")

    monkeypatch.setattr(trigger, "run_job", boom)
    r = c.post("/procesar", json={"prefix": "yaguas/2026-10-18"})
    assert r.status_code == 502 and "403" not in r.text


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"ok": True}
