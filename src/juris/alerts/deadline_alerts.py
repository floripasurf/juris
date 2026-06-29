"""Deadline alert pipeline — flags approaching/overdue deadlines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from juris.prazo.engine import Prazo, PrazoReport, StatusPrazo


class AlertLevel(StrEnum):
    """Alert urgency level."""

    CRITICAL = "critical"  # Vencido or today
    WARNING = "warning"    # 1-3 dias úteis
    INFO = "info"          # 4+ dias úteis


@dataclass(frozen=True, slots=True)
class DeadlineAlert:
    """A single alert for a deadline."""

    prazo: Prazo
    level: AlertLevel
    message: str

    @property
    def short_message(self) -> str:
        return f"[{self.level.value.upper()}] {self.prazo.rule.nome}: {self.prazo.data_limite.strftime('%d/%m')}"


@dataclass(frozen=True, slots=True)
class AlertBatch:
    """A batch of alerts for a processo."""

    numero_cnj: str
    tribunal: str
    generated_at: date
    alerts: list[DeadlineAlert] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.alerts if a.level == AlertLevel.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for a in self.alerts if a.level == AlertLevel.WARNING)

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    @property
    def summary(self) -> str:
        if not self.alerts:
            return f"{self.numero_cnj}: sem alertas"
        c = self.critical_count
        w = self.warning_count
        i = len(self.alerts) - c - w
        parts = []
        if c:
            parts.append(f"{c} critico(s)")
        if w:
            parts.append(f"{w} atencao")
        if i:
            parts.append(f"{i} info")
        return f"{self.numero_cnj}: {', '.join(parts)}"


def _prazo_to_alert_level(prazo: Prazo) -> AlertLevel:
    """Map a prazo status to an alert level."""
    if prazo.status in (StatusPrazo.VENCIDO, StatusPrazo.URGENTE):
        return AlertLevel.CRITICAL
    if prazo.status == StatusPrazo.PROXIMO:
        return AlertLevel.WARNING
    return AlertLevel.INFO


def _build_message(prazo: Prazo) -> str:
    """Build a human-readable alert message."""
    if prazo.status == StatusPrazo.VENCIDO:
        return (
            f"PRAZO VENCIDO: {prazo.rule.nome} venceu em "
            f"{prazo.data_limite.strftime('%d/%m/%Y')} "
            f"({abs(prazo.dias_uteis_restantes)} dias úteis atrás). "
            f"Base legal: {prazo.rule.base_legal}."
        )
    if prazo.status == StatusPrazo.URGENTE:
        return (
            f"PRAZO HOJE: {prazo.rule.nome} vence HOJE "
            f"({prazo.data_limite.strftime('%d/%m/%Y')}). "
            f"Ação: {prazo.rule.tipo_acao.value}. "
            f"Base legal: {prazo.rule.base_legal}."
        )
    if prazo.status == StatusPrazo.PROXIMO:
        return (
            f"ATENÇÃO: {prazo.rule.nome} vence em "
            f"{prazo.dias_uteis_restantes} dia(s) útil(eis) "
            f"({prazo.data_limite.strftime('%d/%m/%Y')}). "
            f"Ação: {prazo.rule.tipo_acao.value}. "
            f"Base legal: {prazo.rule.base_legal}."
        )
    return (
        f"{prazo.rule.nome}: vence em "
        f"{prazo.dias_uteis_restantes} dias úteis "
        f"({prazo.data_limite.strftime('%d/%m/%Y')}). "
        f"Ação: {prazo.rule.tipo_acao.value}."
    )


def generate_alerts(
    report: PrazoReport,
    include_info: bool = False,
) -> AlertBatch:
    """Generate alerts from a PrazoReport.

    Args:
        report: Computed prazo report.
        include_info: If True, include INFO-level alerts (non-urgent).
                     Defaults to False (only CRITICAL and WARNING).

    Returns:
        AlertBatch with alerts sorted by urgency.
    """
    alerts: list[DeadlineAlert] = []

    for prazo in report.prazos:
        if prazo.status == StatusPrazo.CUMPRIDO:
            continue

        level = _prazo_to_alert_level(prazo)

        if not include_info and level == AlertLevel.INFO:
            continue

        alerts.append(DeadlineAlert(
            prazo=prazo,
            level=level,
            message=_build_message(prazo),
        ))

    # Sort: critical first, then warning, then info
    level_order = {AlertLevel.CRITICAL: 0, AlertLevel.WARNING: 1, AlertLevel.INFO: 2}
    alerts.sort(key=lambda a: (level_order.get(a.level, 9), a.prazo.data_limite))

    return AlertBatch(
        numero_cnj=report.numero_cnj,
        tribunal=report.tribunal,
        generated_at=report.computed_at,
        alerts=alerts,
    )
