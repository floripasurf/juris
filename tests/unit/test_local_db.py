"""Tests for the local SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from juris.persistence.local_db import LocalDB


class TestLocalDB:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        assert db.path.exists()

    def test_upsert_processo_creates(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("1234567-89.2026.8.13.0001", "tjmg", classe="Cível")
        assert pid
        proc = db.get_processo_by_cnj("1234567-89.2026.8.13.0001")
        assert proc is not None
        assert proc.tribunal_id == "tjmg"
        assert proc.classe == "Cível"

    def test_upsert_processo_updates(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid1 = db.upsert_processo("123", "tjmg", classe="A")
        pid2 = db.upsert_processo("123", "tjmg", classe="B")
        assert pid1 == pid2
        proc = db.get_processo_by_cnj("123")
        assert proc.classe == "B"

    def test_insert_movimentos_dedup(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        mov = {"data_hora": dt, "tipo": "nacional", "codigo_nacional": 132, "id_movimento": "m1"}

        count1 = db.insert_movimentos(pid, [mov])
        assert count1 == 1

        count2 = db.insert_movimentos(pid, [mov])
        assert count2 == 0  # Deduped

    def test_insert_movimentos_multiple(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        movs = [
            {"data_hora": datetime(2026, 4, 1, tzinfo=UTC), "tipo": "nacional", "codigo_nacional": 132, "id_movimento": "m1"},
            {"data_hora": datetime(2026, 4, 2, tzinfo=UTC), "tipo": "nacional", "codigo_nacional": 11, "id_movimento": "m2"},
        ]
        count = db.insert_movimentos(pid, movs)
        assert count == 2

    def test_upsert_prazo(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        prazo_id = db.upsert_prazo(
            processo_id=pid,
            numero_cnj="123",
            rule_nome="Apelação",
            data_inicio=datetime(2026, 4, 1, tzinfo=UTC),
            data_limite=datetime(2026, 4, 22, tzinfo=UTC),
            status="aberto",
            urgencia="alta",
        )
        assert prazo_id

        prazos = db.get_pending_prazos("123")
        assert len(prazos) == 1
        assert prazos[0].rule_nome == "Apelação"

    def test_upsert_prazo_updates_status(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        dt_start = datetime(2026, 4, 1, tzinfo=UTC)
        dt_end = datetime(2026, 4, 22, tzinfo=UTC)

        id1 = db.upsert_prazo(pid, "123", "Apelação", dt_start, dt_end, status="aberto")
        id2 = db.upsert_prazo(pid, "123", "Apelação", dt_start, dt_end, status="vencido")
        assert id1 == id2

        prazos = db.get_all_prazos("123")
        assert len(prazos) == 1
        assert prazos[0].status == "vencido"

    def test_log_sync(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        db.log_sync("123", "tjmg", "datajud", success=True, new_movimentos=5)
        last = db.get_last_sync("123")
        assert last is not None

    def test_get_last_sync_none(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        assert db.get_last_sync("nonexistent") is None

    def test_get_known_movimento_keys(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        db.insert_movimentos(pid, [
            {"data_hora": dt, "tipo": "nacional", "codigo_nacional": 132, "id_movimento": "m1"},
        ])
        keys = db.get_known_movimento_keys(pid)
        assert len(keys) == 1
        # SQLite strips tzinfo, so compare without it
        key = next(iter(keys))
        assert key[1] == 132
        assert key[2] == "m1"

    def test_get_all_processos(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        db.upsert_processo("aaa", "tjmg")
        db.upsert_processo("bbb", "tjsp")
        procs = db.get_all_processos()
        assert len(procs) == 2

    def test_get_pending_prazos_excludes_cumprido(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("123", "tjmg")
        dt = datetime(2026, 4, 1, tzinfo=UTC)
        db.upsert_prazo(pid, "123", "A", dt, dt, status="aberto")
        db.upsert_prazo(pid, "123", "B", dt, dt, status="cumprido")
        pending = db.get_pending_prazos("123")
        assert len(pending) == 1
        assert pending[0].rule_nome == "A"
