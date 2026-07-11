"""Production smoke test: tenant A can never see tenant B's data.

Exercises the real HTTP surface with two authenticated tenants and asserts strict
isolation across processos, filing status, and connect jobs.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from juris.web.app import _localdb_for_path, app
from juris.web.auth import Tenant, default_registry, hash_api_key, tenant_db_path


@pytest.fixture
def two_tenants(monkeypatch, tmp_path):
    """Configure tenants A and B with API keys; isolated storage under tmp."""
    tenants = tmp_path / "tenants.json"
    tenants.write_text(
        json.dumps({"escritorio-a": hash_api_key("key-a"), "escritorio-b": hash_api_key("key-b")}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    from juris.web.app import _connect_job_store

    default_registry.cache_clear()
    _localdb_for_path.cache_clear()
    _connect_job_store.cache_clear()  # else a prior test's (deleted) tmp DB path leaks
    yield {"a": {"X-API-Key": "key-a"}, "b": {"X-API-Key": "key-b"}}
    default_registry.cache_clear()
    _localdb_for_path.cache_clear()
    _connect_job_store.cache_clear()


def test_tenant_b_cannot_see_tenant_a_processos(two_tenants) -> None:
    client = TestClient(app)
    # seed a processo in tenant A's own store
    db_a = _localdb_for_path(str(tenant_db_path(Tenant("escritorio-a"))))
    db_a.upsert_processo("5082351-40.2017.8.13.0024", "tjmg", classe="Cobrança")

    a = client.get("/api/processos", headers=two_tenants["a"]).json()
    b = client.get("/api/processos", headers=two_tenants["b"]).json()

    assert len(a["processos"]) == 1  # A sees its own
    assert b["processos"] == []  # B sees NOTHING of A's


def test_tenant_b_cannot_read_tenant_a_connect_job(two_tenants) -> None:
    from juris.web.app import _connect_job_store

    client = TestClient(app)
    _connect_job_store().create("job-a", "escritorio-a")

    # B polling A's job id must 404 (ownership checked on read)
    assert client.get("/api/connect/job-a", headers=two_tenants["b"]).status_code == 404
    assert client.get("/api/connect/job-a", headers=two_tenants["a"]).status_code == 200


def test_tenant_b_cannot_see_tenant_a_filing_status(two_tenants, tmp_path) -> None:
    client = TestClient(app)
    # seed a pending filing in A's tenant-scoped filing root
    pending = tmp_path / "tenants" / "escritorio-a" / "filings" / "cnj" / "20260701_pending"
    pending.mkdir(parents=True)

    a = client.get("/api/filing/status", headers=two_tenants["a"]).json()
    b = client.get("/api/filing/status", headers=two_tenants["b"]).json()

    assert any(p["receipt_id"] == "20260701_pending" for p in a["pending"])  # A sees its own
    assert b["pending"] == []  # B sees NOTHING of A's
