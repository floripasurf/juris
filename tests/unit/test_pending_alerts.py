"""Tests for pending deadline alert delivery."""

from __future__ import annotations

from datetime import UTC, date, datetime

from juris.alerts.deadline_alerts import AlertBatch, AlertLevel
from juris.alerts.delivery import AlertDelivery, AlertEmailConfig
from juris.alerts.pending import send_pending_deadline_alerts
from juris.persistence.local_db import LocalDB


class _FakeDelivery(AlertDelivery):
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.batches: list[AlertBatch] = []

    async def send_alert_batch(self, batch: AlertBatch) -> bool:
        self.batches.append(batch)
        return self.ok


def _configured_smtp() -> AlertEmailConfig:
    return AlertEmailConfig(
        smtp_host="smtp.example.test",
        from_address="juris@example.test",
        to_addresses=["adv@example.test"],
    )


def test_send_pending_deadline_alerts_builds_batches_from_local_db(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")
    processo_id = db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
    db.upsert_prazo(
        processo_id,
        "1234567-89.2026.8.13.0001",
        "Apelacao",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 2, tzinfo=UTC),
        status="urgente",
        tipo_acao="recorrer",
        categoria="sentenca",
        urgencia="critica",
        rule_base_legal="Art. 1.003 §5º CPC",
        dias_uteis_total=15,
    )
    db.upsert_prazo(
        processo_id,
        "1234567-89.2026.8.13.0001",
        "Prazo aberto",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 20, tzinfo=UTC),
        status="aberto",
        tipo_acao="manifestar",
        categoria="intimacao",
        urgencia="baixa",
        rule_base_legal="CPC",
        dias_uteis_total=15,
    )
    delivery = _FakeDelivery()

    summary = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=delivery,
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )

    assert summary.processos_checked == 1
    assert summary.batches == 1
    assert summary.alerts == 1
    assert summary.suppressed == 0
    assert summary.sent == 1
    assert delivery.batches[0].alerts[0].level == AlertLevel.CRITICAL


def test_send_pending_deadline_alerts_reports_delivery_failures(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")
    processo_id = db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
    db.upsert_prazo(
        processo_id,
        "1234567-89.2026.8.13.0001",
        "Manifestacao",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 3, tzinfo=UTC),
        status="proximo",
        tipo_acao="manifestar",
    )

    summary = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=_FakeDelivery(ok=False),
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )

    assert summary.failed == 1
    assert summary.sent == 0


def test_send_pending_deadline_alerts_dedupes_successful_deliveries(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")
    processo_id = db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
    db.upsert_prazo(
        processo_id,
        "1234567-89.2026.8.13.0001",
        "Manifestacao",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 3, tzinfo=UTC),
        status="proximo",
        tipo_acao="manifestar",
    )
    delivery = _FakeDelivery()

    first = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=delivery,
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )
    second = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=delivery,
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )

    assert first.sent == 1
    assert second.sent == 0
    assert second.batches == 0
    assert second.alerts == 0
    assert second.suppressed == 1
    assert len(delivery.batches) == 1


def test_failed_delivery_is_not_marked_as_sent(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")
    processo_id = db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
    db.upsert_prazo(
        processo_id,
        "1234567-89.2026.8.13.0001",
        "Manifestacao",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 3, tzinfo=UTC),
        status="proximo",
        tipo_acao="manifestar",
    )

    failed = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=_FakeDelivery(ok=False),
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )
    successful_delivery = _FakeDelivery()
    retried = run_async(
        send_pending_deadline_alerts(
            db=db,
            delivery=successful_delivery,
            config=_configured_smtp(),
            today=date(2026, 7, 1),
        )
    )

    assert failed.failed == 1
    assert retried.sent == 1
    assert retried.suppressed == 0
    assert len(successful_delivery.batches) == 1


def test_send_pending_deadline_alerts_skips_when_smtp_unconfigured(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")
    summary = run_async(
        send_pending_deadline_alerts(
            db=db,
            config=AlertEmailConfig(smtp_host="", from_address="", to_addresses=[]),
        )
    )

    assert summary.smtp_configured is False
    assert summary.processos_checked == 0
    assert summary.sent == 0


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
