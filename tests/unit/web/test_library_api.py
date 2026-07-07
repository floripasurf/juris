"""Biblioteca do Escritório (L5): GET /api/library, busca com tipo/uso, cobertura.

Reusa o harness ``tenant_env`` de ``test_corpus_upload.py`` (payloads T2 já
validados: peça do escritório com ``uso="estilo"`` e acórdão publicado com
``uso="fundamento"``).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.auth import default_registry, hash_api_key

TEXTO_PECA = (
    "CONTESTAÇÃO. COBRANÇA. HONORÁRIOS SUCUMBENCIAIS CONTRA A FAZENDA "
    "PÚBLICA. Modelo interno do escritório para fixação por equidade. " * 20
)
TEXTO_ACORDAO = (
    "EMENTA: APELAÇÃO CÍVEL. COBRANÇA. HONORÁRIOS SUCUMBENCIAIS CONTRA A "
    "FAZENDA PÚBLICA. Fixação por equidade quando o proveito econômico for "
    "inestimável. Recurso provido. " * 20
)


@pytest.fixture
def tenant_env(monkeypatch, tmp_path):
    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": hash_api_key("key-a")}), encoding="utf-8")
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("JURIS_REPERTORY_PATH", str(tmp_path / "repertory.db"))
    default_registry.cache_clear()
    yield {"headers": {"X-API-Key": "key-a"}, "repertory": tmp_path / "repertory.db"}
    default_registry.cache_clear()


def _upload_peca(client: TestClient, headers: dict[str, str]) -> None:
    payload = {
        "title": "Contestação modelo — cobrança",
        "source_type": "peca_escritorio",
        "source_date": "2025-11-10",
        "source_publisher": "Escritório A",
        "provenance_kind": "acervo_do_escritorio",
        "tipo_peticao": "contestacao",
        "area": "civel",
        "source_text": TEXTO_PECA,
    }
    resp = client.post("/api/corpus/upload", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text


def _upload_acordao(client: TestClient, headers: dict[str, str]) -> None:
    payload = {
        "title": "Sentença — Cobrança 0001",
        "source_type": "acordao_publicado",
        "source_date": "2024-05-13",
        "source_url": "https://pje.tjmg.jus.br/consulta/0001234",
        "tribunal": "tjmg",
        "tema": "honorarios",
        "source_text": TEXTO_ACORDAO,
    }
    resp = client.post("/api/corpus/upload", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text


def test_library_lista_fontes_do_tenant(tenant_env) -> None:
    client = TestClient(app)
    _upload_peca(client, tenant_env["headers"])
    _upload_acordao(client, tenant_env["headers"])

    resp = client.get("/api/library", headers=tenant_env["headers"])
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_type = {i["source_type"]: i for i in items}
    assert by_type["peca_escritorio"]["uso"] == "estilo"
    assert by_type["peca_escritorio"]["tipo_peticao"] == "contestacao"
    assert by_type["acordao_publicado"]["uso"] == "fundamento"


def test_library_coverage_por_tipo_peticao(tenant_env) -> None:
    client = TestClient(app)
    _upload_peca(client, tenant_env["headers"])

    resp = client.get("/api/library", headers=tenant_env["headers"])
    assert resp.status_code == 200
    coverage = resp.json()["coverage"]["coverage"]
    assert coverage["tipo_peticao"]["contestacao"] == 1
    assert coverage["uso"]["estilo"] == 1


def test_library_sem_chave_e_401(tenant_env) -> None:
    client = TestClient(app)
    resp = client.get("/api/library")
    assert resp.status_code == 401


def test_search_agrupavel_por_uso(tenant_env) -> None:
    client = TestClient(app)
    _upload_peca(client, tenant_env["headers"])
    _upload_acordao(client, tenant_env["headers"])

    sem = client.get(
        "/api/corpus/search?q=honorarios", headers=tenant_env["headers"]
    ).json()
    assert all(r.get("uso") != "estilo" for r in sem["results"])

    com = client.get(
        "/api/corpus/search?q=honorarios&include_estilo=1", headers=tenant_env["headers"]
    ).json()
    assert any(r.get("uso") == "estilo" for r in com["results"])
