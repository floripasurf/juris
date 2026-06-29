"""Tests for the durable connect-job store (survives restart, tenant-scoped)."""

from __future__ import annotations

from juris.web.connect_jobs import ConnectJobStore


def test_create_then_get_returns_running(tmp_path) -> None:
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-1", "escritorio-a")
    job = store.get("job-1")
    assert job is not None
    assert job["status"] == "running"
    assert job["tenant_id"] == "escritorio-a"


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
