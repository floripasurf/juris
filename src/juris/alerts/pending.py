"""Build and deliver pending deadline alerts from the local store."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from juris.alerts.deadline_alerts import AlertBatch, AlertLevel, DeadlineAlert
from juris.alerts.delivery import AlertDelivery, AlertEmailConfig
from juris.config import Settings, get_settings
from juris.core.observability import get_logger
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.persistence.local_db import LocalDB, PrazoLocal, ProcessoLocal
from juris.prazo.engine import Prazo, StatusPrazo
from juris.prazo.rules import PrazoRule, TipoAcao

logger = get_logger(__name__)

# The one tenant that pre-dates per-tenant alert recipients: its overnight/alert
# delivery must keep working off the global ALERT_TO_ADDRESSES until it (or every
# other tenant) configures its own list via `juris tenant alert-emails`.
PILOT_TENANT_ID = "escritorio-piloto"


@dataclass(slots=True)
class PendingAlertDeliverySummary:
    """Delivery result for pending prazo alerts."""

    processos_checked: int = 0
    batches: int = 0
    alerts: int = 0
    suppressed: int = 0
    sent: int = 0
    failed: int = 0
    smtp_configured: bool = False
    no_recipients: bool = False


def alert_email_config_from_settings(
    settings: Settings | None = None, *, to_addresses: list[str] | None = None
) -> AlertEmailConfig:
    """Build the SMTP alert config from Juris settings.

    ``to_addresses``, when given, overrides the global ``ALERT_TO_ADDRESSES``
    setting entirely — this is how a per-tenant recipient list (from
    :func:`alert_recipients_for_tenant`) reaches the SMTP layer.
    """
    settings = settings or get_settings()
    resolved_to = (
        to_addresses
        if to_addresses is not None
        else [address.strip() for address in settings.alert_to_addresses.split(",") if address.strip()]
    )
    return AlertEmailConfig(
        smtp_host=settings.alert_smtp_host,
        smtp_port=settings.alert_smtp_port,
        smtp_user=settings.alert_smtp_user,
        smtp_password=settings.alert_smtp_password.get_secret_value() if settings.alert_smtp_password else "",
        from_address=settings.alert_from_address,
        to_addresses=resolved_to,
    )


def alert_recipients_for_tenant(
    tenant_id: str, *, path: Path | None = None, settings: Settings | None = None
) -> list[str]:
    """Resolve alert recipients for one tenant.

    Per-tenant list from tenants.json (:func:`~juris.web.trial_access.alert_emails_for_tenant`)
    takes priority. Only :data:`PILOT_TENANT_ID` falls back to the global
    ``ALERT_TO_ADDRESSES`` when it has no list configured yet — every other
    tenant with an empty list simply gets no alerts (no silent broadcast to a
    global address that isn't theirs).
    """
    from juris.web.trial_access import alert_emails_for_tenant

    recipients = alert_emails_for_tenant(tenant_id, path=path)
    if recipients or tenant_id != PILOT_TENANT_ID:
        return recipients
    settings = settings or get_settings()
    return [address.strip() for address in settings.alert_to_addresses.split(",") if address.strip()]


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _status(value: str) -> StatusPrazo:
    try:
        return StatusPrazo(value)
    except ValueError:
        return StatusPrazo.ABERTO


def _tipo_acao(value: str | None) -> TipoAcao:
    try:
        return TipoAcao(value or "")
    except ValueError:
        return TipoAcao.MANIFESTAR


def _categoria(value: str | None) -> CategoriaSemantica:
    try:
        return CategoriaSemantica(value or "")
    except ValueError:
        return CategoriaSemantica.UNCLASSIFIED


def _urgencia(value: str | None) -> Urgencia:
    try:
        return Urgencia(value or "")
    except ValueError:
        return Urgencia.NENHUMA


def _level_for_status(status: StatusPrazo) -> AlertLevel | None:
    if status in (StatusPrazo.VENCIDO, StatusPrazo.URGENTE):
        return AlertLevel.CRITICAL
    if status == StatusPrazo.PROXIMO:
        return AlertLevel.WARNING
    return None


def _prazo_from_local(prazo: PrazoLocal) -> Prazo:
    categoria = _categoria(prazo.categoria)
    rule = PrazoRule(
        nome=prazo.rule_nome,
        categoria_trigger=categoria,
        codigo_tpu=None,
        dias_uteis=prazo.dias_uteis_total or 0,
        tipo_acao=_tipo_acao(prazo.tipo_acao),
        base_legal=prazo.rule_base_legal or "",
    )
    return Prazo(
        movimento_id=prazo.id,
        numero_cnj=prazo.numero_cnj,
        rule=rule,
        data_inicio=_as_date(prazo.data_inicio),
        data_limite=_as_date(prazo.data_limite),
        dias_uteis_total=prazo.dias_uteis_total or 0,
        dias_uteis_restantes=0,
        status=_status(prazo.status),
        categoria=categoria,
        urgencia=_urgencia(prazo.urgencia),
    )


def _alert_key(numero_cnj: str, prazo: PrazoLocal, level: AlertLevel) -> str:
    """Stable fingerprint for deduping delivered deadline alerts.

    Include level/status/date so an alert can be resent when it escalates from
    warning to critical or when the computed deadline materially changes.
    """
    raw = "|".join(
        (
            numero_cnj,
            prazo.id,
            prazo.rule_nome,
            _as_date(prazo.data_limite).isoformat(),
            prazo.status,
            level.value,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _alert_record(numero_cnj: str, prazo: PrazoLocal, level: AlertLevel) -> dict[str, str]:
    return {
        "alert_key": _alert_key(numero_cnj, prazo, level),
        "numero_cnj": numero_cnj,
        "prazo_id": prazo.id,
        "level": level.value,
    }


def build_pending_alert_batch(
    processo: ProcessoLocal,
    pending: Iterable[PrazoLocal],
    *,
    generated_at: date | None = None,
    skip_alert_keys: set[str] | None = None,
) -> AlertBatch | None:
    """Build a deliverable alert batch from persisted pending prazos."""
    skip_alert_keys = skip_alert_keys or set()
    alerts: list[DeadlineAlert] = []
    for prazo_local in pending:
        prazo = _prazo_from_local(prazo_local)
        level = _level_for_status(prazo.status)
        if level is None:
            continue
        if _alert_key(processo.numero_cnj, prazo_local, level) in skip_alert_keys:
            continue
        alerts.append(
            DeadlineAlert(
                prazo=prazo,
                level=level,
                message=f"{prazo.rule.nome}: {prazo.status.value}",
            )
        )

    if not alerts:
        return None

    return AlertBatch(
        numero_cnj=processo.numero_cnj,
        tribunal=processo.tribunal_id,
        generated_at=generated_at or date.today(),
        alerts=alerts,
    )


async def send_pending_deadline_alerts(
    *,
    db: LocalDB,
    delivery: AlertDelivery | None = None,
    config: AlertEmailConfig | None = None,
    today: date | None = None,
) -> PendingAlertDeliverySummary:
    """Send all critical/warning pending prazo alerts via the configured delivery.

    ``db`` is required (no implicit ``LocalDB()`` fallback) so every caller is
    explicit about which tenant's database it is delivering for — see
    :func:`alert_recipients_for_tenant` for how the matching recipient list is
    resolved per tenant.
    """
    config = config if config is not None else alert_email_config_from_settings()
    # "SMTP not configured" and "this tenant has no recipients" are distinct
    # operational states (one is infra, the other is per-tenant setup) — kept as
    # separate summary fields rather than collapsed into `config.is_configured`.
    smtp_configured = bool(config.smtp_host and config.from_address)
    no_recipients = not config.to_addresses
    summary = PendingAlertDeliverySummary(smtp_configured=smtp_configured, no_recipients=no_recipients)

    if delivery is None:
        if not smtp_configured:
            logger.warning("pending_alerts_smtp_not_configured")
            return summary
        if no_recipients:
            logger.warning("alert_sem_destinatario")
            return summary

    delivery = delivery or AlertDelivery(config)
    processos = db.get_all_processos()
    summary.processos_checked = len(processos)

    for processo in processos:
        pending = db.get_pending_prazos(processo.numero_cnj)
        alert_records: list[dict[str, str]] = []
        for prazo_local in pending:
            level = _level_for_status(_status(prazo_local.status))
            if level is None:
                continue
            alert_records.append(_alert_record(processo.numero_cnj, prazo_local, level))

        sent_keys = db.get_sent_alert_keys({record["alert_key"] for record in alert_records})
        summary.suppressed += len(sent_keys)
        batch = build_pending_alert_batch(processo, pending, generated_at=today, skip_alert_keys=sent_keys)
        if batch is None:
            continue
        pending_records = [record for record in alert_records if record["alert_key"] not in sent_keys]

        summary.batches += 1
        summary.alerts += len(batch.alerts)
        if await delivery.send_alert_batch(batch):
            db.mark_alerts_sent(pending_records)
            summary.sent += 1
        else:
            summary.failed += 1

    logger.info(
        "pending_alerts_delivery_done",
        processos=summary.processos_checked,
        batches=summary.batches,
        alerts=summary.alerts,
        suppressed=summary.suppressed,
        sent=summary.sent,
        failed=summary.failed,
    )
    return summary
