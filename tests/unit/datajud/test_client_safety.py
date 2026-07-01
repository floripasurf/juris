"""Tests for DataJud client safety integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from juris.datajud.client import _party_log_fields, buscar_parte_todos_tribunais, consultar_processo
from juris.datajud.safety import BatchGuardError


def _response(payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://api-publica.datajud.cnj.jus.br/api_publica_tjmg/_search")
    return httpx.Response(200, json=payload, request=request)


def _payload(numero: str = "00012345620268130001") -> dict:
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "numeroProcesso": numero,
                        "movimentos": [],
                    }
                }
            ]
        }
    }


def test_consultar_processo_uses_cache_on_second_call(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    audit_path = tmp_path / "audit.jsonl"
    post = MagicMock(return_value=_response(_payload()))
    monkeypatch.setattr("httpx.post", post)

    first = consultar_processo(
        "0001234-56.2026.8.13.0001",
        "tjmg",
        cache_dir=cache_dir,
        audit_path=audit_path,
    )
    second = consultar_processo(
        "0001234-56.2026.8.13.0001",
        "tjmg",
        cache_dir=cache_dir,
        audit_path=audit_path,
    )

    assert first == second
    assert post.call_count == 1
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [e["details"]["cache_hit"] for e in entries] == [False, True]
    assert all(e["event_type"] == "datajud.request" for e in entries)


def test_consultar_processo_no_cache_forces_live_call(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    audit_path = tmp_path / "audit.jsonl"
    post = MagicMock(side_effect=[_response(_payload("1")), _response(_payload("2"))])
    monkeypatch.setattr("httpx.post", post)

    consultar_processo(
        "0001234-56.2026.8.13.0001",
        "tjmg",
        cache_dir=cache_dir,
        audit_path=audit_path,
        use_cache=False,
    )
    consultar_processo(
        "0001234-56.2026.8.13.0001",
        "tjmg",
        cache_dir=cache_dir,
        audit_path=audit_path,
        use_cache=False,
    )

    assert post.call_count == 2
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [e["details"]["cache_hit"] for e in entries] == [False, False]


def test_consultar_processo_waits_on_rate_limiter(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    audit_path = tmp_path / "audit.jsonl"
    post = MagicMock(return_value=_response(_payload()))
    limiter = MagicMock()
    monkeypatch.setattr("httpx.post", post)

    consultar_processo(
        "0001234-56.2026.8.13.0001",
        "tjmg",
        cache_dir=cache_dir,
        audit_path=audit_path,
        use_cache=False,
        rate_limiter=limiter,
    )

    limiter.wait.assert_called_once_with()


def test_buscar_parte_todos_tribunais_requires_confirmation_for_large_fanout(monkeypatch) -> None:
    client = MagicMock()
    monkeypatch.setattr("httpx.Client", client)

    with pytest.raises(BatchGuardError):
        buscar_parte_todos_tribunais(
            nome="Maria Silva",
            tribunais=[
                "tjmg",
                "tjsp",
                "tjrj",
                "tjrs",
                "tjpr",
                "tjsc",
                "tjba",
                "tjgo",
                "tjpe",
                "tjce",
            ],
        )

    client.assert_not_called()


def test_party_search_log_fields_do_not_expose_party_pii() -> None:
    fields = _party_log_fields(nome="Maria Silva", cpf="123.456.789-00")
    dumped = json.dumps(fields, ensure_ascii=False)

    assert fields == {
        "nome_present": True,
        "nome_chars": 11,
        "cpf_present": True,
        "cpf_mask": "***00",
    }
    assert "Maria" not in dumped
    assert "Silva" not in dumped
    assert "123.456.789-00" not in dumped
    assert "12345678900" not in dumped
