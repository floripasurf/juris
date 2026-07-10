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


def _upload_peca(
    client: TestClient,
    headers: dict[str, str],
    *,
    area: str = "civel",
    title: str = "Contestação modelo — cobrança",
    text: str = TEXTO_PECA,
) -> None:
    payload = {
        "title": title,
        "source_type": "peca_escritorio",
        "source_date": "2025-11-10",
        "source_publisher": "Escritório A",
        "provenance_kind": "acervo_do_escritorio",
        "tipo_peticao": "contestacao",
        "area": area,
        "source_text": text,
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
    assert by_type["peca_escritorio"]["area"] == "civel"
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


def test_erasure_remove_biblioteca_no_nivel_certo(tenant_env, tmp_path) -> None:
    """LGPD erasure at the right level: the tenant's library chunks in
    repertory.db are wiped AND the old key stops authenticating (401) —
    a "sim, mas lista vazia" (200) result would mean data was gone but
    access wasn't, which is erasure at the wrong level."""
    import sqlite3

    from juris.ops.erasure import build_tenant_erasure_plan, execute_tenant_erasure

    client = TestClient(app)
    _upload_peca(client, tenant_env["headers"])

    plan = build_tenant_erasure_plan("escritorio-a")
    result = execute_tenant_erasure(plan, confirmation=plan.confirmation_phrase)
    assert result.access_revoked is True

    # (b) chave antiga rejeitada — tenant apagado não autentica.
    resp = client.get("/api/library", headers=tenant_env["headers"])
    assert resp.status_code == 401

    # (c) repertory.db sem chunks do tenant.
    conn = sqlite3.connect(tenant_env["repertory"])
    try:
        n = conn.execute(
            "SELECT count(*) FROM chunks WHERE tenant_id = 'escritorio-a'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0

    # (d) certificado registrado.
    log_path = tmp_path / "compliance-erasure.jsonl"
    assert "escritorio-a" in log_path.read_text(encoding="utf-8")


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
    assert any(r.get("area") == "civel" for r in com["results"])


def test_search_filtra_biblioteca_privada_por_area(tenant_env) -> None:
    client = TestClient(app)
    _upload_peca(
        client,
        tenant_env["headers"],
        area="trabalhista",
        title="Contestação trabalhista",
        text="contestacao honorarios trabalhista audiencia verbas rescisorias " * 20,
    )
    _upload_peca(
        client,
        tenant_env["headers"],
        area="empresarial",
        title="Contestação empresarial",
        text="contestacao honorarios empresarial contrato quotas sociedade " * 20,
    )

    resp = client.get(
        "/api/corpus/search?q=contestacao&include_estilo=1&area=empresarial",
        headers=tenant_env["headers"],
    )

    assert resp.status_code == 200
    assert any(r["area"] == "empresarial" for r in resp.json()["results"])
    assert "trabalhista" not in {r["area"] for r in resp.json()["results"]}
