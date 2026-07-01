"""Tests for the durable connect-job store (survives restart, tenant-scoped)."""

from __future__ import annotations

import sqlite3

from juris.web.connect_jobs import ConnectJobStore


def test_default_path_honors_juris_home(tmp_path, monkeypatch) -> None:
    from juris.web.connect_jobs import default_connect_jobs_path

    monkeypatch.setenv("JURIS_HOME", str(tmp_path))

    assert default_connect_jobs_path() == tmp_path / "connect_jobs.db"


def test_create_then_get_returns_running(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-1", "escritorio-a")
    job = store.get("job-1")
    assert job is not None
    assert job["status"] == "running"
    assert job["tenant_id"] == "escritorio-a"


def test_create_rejects_duplicate_job_id(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-1", "escritorio-a")

    try:
        store.create("job-1", "escritorio-b")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("job_id duplicado não deve sobrescrever outro tenant")

    assert store.get("job-1")["tenant_id"] == "escritorio-a"


def test_mark_done_persists_result_across_instances(tmp_path) -> None:
    path = tmp_path / "jobs.db"
    ConnectJobStore(path).create("job-1", "escritorio-a")
    ConnectJobStore(path).mark_done("job-1", {"total_tracked": 5})

    # a fresh store (process restart) still sees the finished job — durable
    reborn = ConnectJobStore(path)
    job = reborn.get("job-1")
    assert job is not None
    assert job["status"] == "done"
    assert job["result"]["total_tracked"] == 5


def test_mark_error_records_message(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-1", "escritorio-a")
    store.mark_error("job-1", "token ausente")
    job = store.get("job-1")
    assert job is not None
    assert job["status"] == "error"
    assert job["error"] == "token ausente"


def test_get_unknown_returns_none(tmp_path) -> None:
    assert ConnectJobStore(tmp_path / "jobs.db").get("nope") is None


def test_evict_old_caps_the_table(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    for i in range(10):
        store.create(f"job-{i}", "escritorio-a")
    store.evict_old(max_jobs=5)
    remaining = [f"job-{i}" for i in range(10) if store.get(f"job-{i}") is not None]
    assert len(remaining) <= 5
    # the newest survive (FIFO drop of the oldest)
    assert store.get("job-9") is not None


def test_evict_old_can_be_scoped_to_one_tenant(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    for i in range(10):
        store.create(f"a-{i}", "escritorio-a")
    for i in range(3):
        store.create(f"b-{i}", "escritorio-b")

    store.evict_old(max_jobs=5, tenant_id="escritorio-a")

    remaining_a = [f"a-{i}" for i in range(10) if store.get(f"a-{i}") is not None]
    remaining_b = [f"b-{i}" for i in range(3) if store.get(f"b-{i}") is not None]
    assert len(remaining_a) <= 5
    assert remaining_b == ["b-0", "b-1", "b-2"]


def test_sweep_stale_marks_old_running_jobs_as_error(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("j", "escritorio-a")

    # a generous cutoff leaves a fresh running job alone
    assert store.sweep_stale(3600) == 0
    assert store.get("j")["status"] == "running"

    # a negative age treats every running job as stale (crash/restart recovery)
    assert store.sweep_stale(-1) == 1
    job = store.get("j")
    assert job["status"] == "error"
    assert "interrompido" in job["error"]
