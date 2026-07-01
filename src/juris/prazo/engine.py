"""Prazo engine — computes deadlines from movements using calendar + rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from juris.agents.analyzer import AnalysisResult
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.calendar import JudicialCalendar
from juris.prazo.rules import PrazoRule, find_applicable_rules


class StatusPrazo(StrEnum):
    """Status of a deadline."""

    ABERTO = "aberto"  # Deadline not yet reached
    PROXIMO = "proximo"  # Within 3 dias úteis of deadline
    URGENTE = "urgente"  # Within 1 dia útil or today
    VENCIDO = "vencido"  # Past the deadline
    CUMPRIDO = "cumprido"  # Marked as fulfilled


@dataclass(frozen=True, slots=True)
class Prazo:
    """A computed deadline for a specific movement."""

    movimento_id: str
    numero_cnj: str
    rule: PrazoRule
    data_inicio: date  # Date the clock starts (dia da intimação/publicação)
    data_limite: date  # Final date for the action
    dias_uteis_total: int
    dias_uteis_restantes: int
    status: StatusPrazo
    categoria: CategoriaSemantica
    urgencia: Urgencia

    @property
    def summary(self) -> str:
        status_emoji = {
            StatusPrazo.ABERTO: "OK",
            StatusPrazo.PROXIMO: "ATENCAO",
            StatusPrazo.URGENTE: "URGENTE",
            StatusPrazo.VENCIDO: "VENCIDO",
            StatusPrazo.CUMPRIDO: "CUMPRIDO",
        }
        tag = status_emoji.get(self.status, "?")
        return (
            f"[{tag}] {self.rule.nome}: "
            f"{self.data_limite.strftime('%d/%m/%Y')} "
            f"({self.dias_uteis_restantes}d úteis) — "
            f"{self.rule.base_legal}"
        )


@dataclass(frozen=True, slots=True)
class RevisaoManual:
    """An actionable movement whose deadline could NOT be computed deterministically.

    Surfaced instead of silently dropped (no rule) or fabricated (missing date), so a
    human reviews it. ``motivo`` ∈ {``data_ausente``, ``sem_regra_de_prazo``}.
    """

    movimento_id: str
    categoria: CategoriaSemantica
    motivo: str
    descricao: str = ""


@dataclass(frozen=True, slots=True)
class PrazoReport:
    """Full deadline report for a processo."""

    numero_cnj: str
    tribunal: str
    computed_at: date
    prazos: list[Prazo] = field(default_factory=list)
    revisao_manual: list[RevisaoManual] = field(default_factory=list)

    @property
    def vencidos(self) -> list[Prazo]:
        return [p for p in self.prazos if p.status == StatusPrazo.VENCIDO]

    @property
    def urgentes(self) -> list[Prazo]:
        return [p for p in self.prazos if p.status in (StatusPrazo.URGENTE, StatusPrazo.PROXIMO)]

    @property
    def abertos(self) -> list[Prazo]:
        return [p for p in self.prazos if p.status == StatusPrazo.ABERTO]

    @property
    def has_critical(self) -> bool:
        return bool(self.vencidos or self.urgentes)

    @property
    def summary(self) -> str:
        if not self.prazos:
            return f"{self.numero_cnj}: sem prazos pendentes"
        v = len(self.vencidos)
        u = len(self.urgentes)
        a = len(self.abertos)
        parts = []
        if v:
            parts.append(f"{v} vencido(s)")
        if u:
            parts.append(f"{u} urgente(s)")
        if a:
            parts.append(f"{a} aberto(s)")
        return f"{self.numero_cnj}: {', '.join(parts)}"


def _compute_status(dias_uteis_restantes: int) -> StatusPrazo:
    """Determine deadline status based on remaining dias úteis."""
    if dias_uteis_restantes < 0:
        return StatusPrazo.VENCIDO
    if dias_uteis_restantes == 0:
        return StatusPrazo.URGENTE
    if dias_uteis_restantes <= 3:
        return StatusPrazo.PROXIMO
    return StatusPrazo.ABERTO


def compute_prazo(
    analysis: AnalysisResult,
    rule: PrazoRule,
    calendar: JudicialCalendar,
    today: date | None = None,
    numero_cnj: str = "",
) -> Prazo:
    """Compute a single deadline from an analyzed movement + rule.

    Args:
        analysis: The analyzed movement result.
        rule: The applicable deadline rule.
        calendar: Judicial calendar for dias úteis computation.
        today: Override for current date (for testing).
        numero_cnj: Case number.

    Returns:
        Computed Prazo with status.
    """
    today = today or date.today()

    # Invariant: undated movements are routed to revisao_manual upstream, never here.
    if analysis.data_hora is None:
        msg = "compute_prazo requires a dated movement; route undated to revisao_manual"
        raise ValueError(msg)

    # Start date: the date of the movement (converted from datetime)
    data_inicio = analysis.data_hora.date()

    # CPC Art. 224 §1º: prazo starts on the first dia útil after the event
    data_limite = calendar.add_dias_uteis(data_inicio, rule.dias_uteis)

    dias_restantes = calendar.dias_uteis_between(today, data_limite)
    if today > data_limite:
        # Lapsed by the calendar — VENCIDO regardless of the business-day delta.
        # (A deadline expiring Friday is lapsed on Saturday even though there are 0
        # dias úteis between them; the old `-0 == 0` misread it as URGENTE.)
        dias_restantes = -calendar.dias_uteis_between(data_limite, today)
        status = StatusPrazo.VENCIDO
    else:
        status = _compute_status(dias_restantes)

    # Override urgency based on deadline status
    if status == StatusPrazo.VENCIDO or status == StatusPrazo.URGENTE:
        urgencia = Urgencia.CRITICA
    elif status == StatusPrazo.PROXIMO:
        urgencia = Urgencia.ALTA
    else:
        urgencia = analysis.urgencia

    return Prazo(
        movimento_id=analysis.movimento_id,
        numero_cnj=numero_cnj,
        rule=rule,
        data_inicio=data_inicio,
        data_limite=data_limite,
        dias_uteis_total=rule.dias_uteis,
        dias_uteis_restantes=dias_restantes,
        status=status,
        categoria=analysis.categoria,
        urgencia=urgencia,
    )


def compute_prazos(
    numero_cnj: str,
    tribunal: str,
    analyses: list[AnalysisResult],
    calendar: JudicialCalendar | None = None,
    today: date | None = None,
    justica: str = "civel",
) -> PrazoReport:
    """Compute all deadlines for a processo's analyzed movements.

    Args:
        numero_cnj: Case number.
        tribunal: Tribunal ID.
        analyses: List of analyzed movements.
        calendar: Judicial calendar (defaults to MG).
        today: Override current date (for testing).
        justica: "civel" or "trabalho".

    Returns:
        PrazoReport with all computed deadlines.
    """
    today = today or date.today()
    calendar = calendar or JudicialCalendar(uf=_tribunal_to_uf(tribunal))

    prazos: list[Prazo] = []
    revisao_manual: list[RevisaoManual] = []

    for analysis in analyses:
        if not analysis.requer_acao:
            continue

        # Missing/unparseable movement date: never fabricate a deadline from it.
        if analysis.data_hora is None:
            revisao_manual.append(
                RevisaoManual(analysis.movimento_id, analysis.categoria, "data_ausente", analysis.descricao)
            )
            continue

        rules = find_applicable_rules(
            analysis.categoria,
            analysis.codigo_tpu,
            justica,
        )

        # Actionable movement that matches no rule: surface for human review, never drop.
        if not rules:
            revisao_manual.append(
                RevisaoManual(analysis.movimento_id, analysis.categoria, "sem_regra_de_prazo", analysis.descricao)
            )
            continue

        for rule in rules:
            prazo = compute_prazo(analysis, rule, calendar, today, numero_cnj)
            prazos.append(prazo)

    # Sort by urgency: vencidos first, then by date
    status_order = {
        StatusPrazo.VENCIDO: 0,
        StatusPrazo.URGENTE: 1,
        StatusPrazo.PROXIMO: 2,
        StatusPrazo.ABERTO: 3,
        StatusPrazo.CUMPRIDO: 4,
    }
    prazos.sort(key=lambda p: (status_order.get(p.status, 9), p.data_limite))

    return PrazoReport(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        computed_at=today,
        prazos=prazos,
        revisao_manual=revisao_manual,
    )


def _tribunal_to_uf(tribunal_id: str) -> str:
    """Extract UF from tribunal ID."""
    _map = {
        "tjmg": "mg",
        "tjsp": "sp",
        "tjrj": "rj",
        "tjba": "ba",
        "tjrs": "rs",
        "tjpr": "pr",
        "tjpe": "pe",
        "tjsc": "sc",
        "tjgo": "go",
        "tjdf": "df",
        "tjce": "ce",
        "tjpa": "pa",
        "tjma": "ma",
        "tjam": "am",
        "tjmt": "mt",
        "tjms": "ms",
        "tjes": "es",
        "tjpb": "pb",
        "tjrn": "rn",
        "tjal": "al",
        "tjpi": "pi",
        "tjse": "se",
        "tjro": "ro",
        "tjac": "ac",
        "tjap": "ap",
        "tjrr": "rr",
        "tjto": "to",
    }
    return _map.get(tribunal_id.lower(), "mg")
