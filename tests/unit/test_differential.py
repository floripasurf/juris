"""Tests for differential read logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from juris.mni.operations.differential import (
    DiffResult,
    detect_new_documents,
    detect_new_movements,
    diff_processo,
)
from juris.mni.parsers.processo import Documento, Movimento, ProcessoDomain


def _mov(hours_ago: int, codigo: int = 60, id_mov: str = "") -> Movimento:
    """Helper to create a Movimento at a given time offset."""
    return Movimento(
        data_hora=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC) - timedelta(hours=hours_ago),
        tipo="nacional",
        codigo_nacional=codigo,
        descricao=f"Mov {codigo}",
        id_movimento=id_mov or f"mov_{hours_ago}_{codigo}",
    )


def _processo(movs: list[Movimento], docs: list[Documento] | None = None) -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="1234567-89.2026.8.13.0001",
        tribunal="tjmg",
        movimentos=movs,
        documentos=docs or [],
    )


class TestDetectNewMovements:
    def test_first_sync_returns_all(self) -> None:
        movs = [_mov(48), _mov(24), _mov(1)]
        result = detect_new_movements(_processo(movs), last_sync_at=None)
        assert len(result) == 3

    def test_no_new_movements(self) -> None:
        movs = [_mov(48), _mov(24)]
        last_sync = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)  # After all movs
        result = detect_new_movements(_processo(movs), last_sync_at=last_sync)
        assert len(result) == 0

    def test_only_new_after_cursor(self) -> None:
        movs = [_mov(72), _mov(48), _mov(24), _mov(1)]
        # Sync was 36 hours ago → should get the last 2 (24h ago and 1h ago)
        last_sync = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC) - timedelta(hours=36)
        result = detect_new_movements(_processo(movs), last_sync_at=last_sync)
        assert len(result) == 2

    def test_dedup_by_key(self) -> None:
        mov = _mov(1, codigo=132, id_mov="abc")
        known_keys = {(mov.data_hora, mov.codigo_nacional, mov.id_movimento)}
        # Even though it's after last_sync, it's already known
        last_sync = datetime(2026, 4, 10, tzinfo=UTC)
        result = detect_new_movements(
            _processo([mov]), last_sync_at=last_sync, known_movimento_keys=known_keys,
        )
        assert len(result) == 0

    def test_mixed_new_and_known(self) -> None:
        old_mov = _mov(1, codigo=60, id_mov="old1")
        new_mov = _mov(0, codigo=132, id_mov="new1")
        known_keys = {(old_mov.data_hora, old_mov.codigo_nacional, old_mov.id_movimento)}
        last_sync = datetime(2026, 4, 10, tzinfo=UTC)
        result = detect_new_movements(
            _processo([old_mov, new_mov]),
            last_sync_at=last_sync,
            known_movimento_keys=known_keys,
        )
        assert len(result) == 1
        assert result[0].id_movimento == "new1"


class TestDetectNewDocuments:
    def test_all_new(self) -> None:
        docs = [
            Documento(id_documento="d1", tipo_documento="Petição"),
            Documento(id_documento="d2", tipo_documento="Sentença"),
        ]
        result = detect_new_documents(_processo([], docs), known_doc_ids=set())
        assert result == ["d1", "d2"]

    def test_some_known(self) -> None:
        docs = [
            Documento(id_documento="d1", tipo_documento="Petição"),
            Documento(id_documento="d2", tipo_documento="Sentença"),
        ]
        result = detect_new_documents(_processo([], docs), known_doc_ids={"d1"})
        assert result == ["d2"]

    def test_all_known(self) -> None:
        docs = [Documento(id_documento="d1", tipo_documento="Petição")]
        result = detect_new_documents(_processo([], docs), known_doc_ids={"d1"})
        assert result == []


class TestDiffProcesso:
    def test_first_sync_has_changes(self) -> None:
        movs = [_mov(24), _mov(1)]
        result = diff_processo(_processo(movs), last_sync_at=None)
        assert result.had_changes
        assert len(result.new_movimentos) == 2
        assert result.total_movimentos_fetched == 2

    def test_no_changes(self) -> None:
        movs = [_mov(48)]
        last_sync = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        result = diff_processo(_processo(movs), last_sync_at=last_sync)
        assert not result.had_changes
        assert len(result.new_movimentos) == 0

    def test_summary_message(self) -> None:
        result = DiffResult(
            numero_cnj="123",
            tribunal_id="tjmg",
            error="Connection failed",
        )
        assert "[ERROR]" in result.summary

        result2 = DiffResult(
            numero_cnj="123",
            tribunal_id="tjmg",
            had_changes=False,
        )
        assert "no changes" in result2.summary
