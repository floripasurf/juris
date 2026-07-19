"""Prazo engine — computes deadlines from movements using calendar + rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum

from juris.agents.analyzer import AnalysisResult
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.calendar import JudicialCalendar
from juris.prazo.rules import PrazoRule, TipoAcao, find_applicable_rules


class StatusPrazo(StrEnum):
    """Status of a deadline."""

    ABERTO = "aberto"  # Deadline not yet reached
    PROXIMO = "proximo"  # Within 3 dias úteis of deadline
    URGENTE = "urgente"  # Within 1 dia útil or today
    VENCIDO = "vencido"  # Past the deadline
    CUMPRIDO = "cumprido"  # Marked as fulfilled


_EMBARGOS_DECLARACAO_RE = re.compile(r"\bembargos?\s+de\s+declara[cç][aã]o\b", re.IGNORECASE)
_EMBARGOS_RESOLUTION_RE = re.compile(
    r"\b(julgad|acolhid|rejeitad|provido|n[aã]o\s+provido|nao\s+provido|decidid|publicad)\w*",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:(?P<br_day>\d{1,2})[/-](?P<br_month>\d{1,2})[/-](?P<br_year>\d{2,4})"
    r"|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))\b"
)
_DJE_AVAILABILITY_RE = re.compile(
    r"\b(disponibilizad\w*|disponibiliza[cç][aã]o)\b.{0,60}\b(dje|di[aá]rio\s+de\s+justi[cç]a)\b",
    re.IGNORECASE,
)
_PUBLICATION_RE = re.compile(r"\b(publicad\w*|publica[cç][aã]o)\b", re.IGNORECASE)
_JOINED_SERVICE_RE = re.compile(
    r"\b(juntad\w*|juntada)\b.{0,80}\b(mandado|aviso\s+de\s+recebimento|a\.?r\.?|ar|carta)\b"
    r"|\b(mandado|aviso\s+de\s+recebimento|a\.?r\.?|ar|carta)\b.{0,80}\b(juntad\w*|juntada)\b",
    re.IGNORECASE,
)
_ELECTRONIC_NOTICE_RE = re.compile(
    r"\b(ci[eê]ncia|confirmad\w*|lida|abert\w*)\b.{0,80}\b(intima[cç][aã]o\s+eletr[oô]nica|pje|portal)\b"
    r"|\b(intima[cç][aã]o\s+eletr[oô]nica|pje|portal)\b.{0,80}\b(ci[eê]ncia|confirmad\w*|lida|abert\w*)\b",
    re.IGNORECASE,
)
_COMPLETED_CITATION_RE = re.compile(
    r"\b(cita[cç][aã]o|citad[oa])\b.{0,80}\b(realizad\w*|cumprid\w*|positiv\w*)\b"
    r"|\b(realizad\w*|cumprid\w*|positiv\w*)\b.{0,80}\b(cita[cç][aã]o|citad[oa])\b",
    re.IGNORECASE,
)
_REOPENED_APPEAL_AFTER_ED_RULE = PrazoRule(
    nome="Apelação (reaberta após embargos de declaração)",
    categoria_trigger=CategoriaSemantica.SENTENCA,
    codigo_tpu=None,
    dias_uteis=15,
    tipo_acao=TipoAcao.RECORRER,
    base_legal="Art. 1.026 CPC c/c Art. 1.003 §5º CPC",
    # Reabertura do prazo recursal comum — não é prazo próprio, então continua
    # elegível à dobra (admite_dobro=True, o default).
)

# Escopo ESTREITO (revisão jurídica externa): só a interlocutória agravável
# (TPU 385 — decisão interlocutória, art. 1.015 CPC) tem regra própria de
# reabertura. Qualquer outra DECISAO_RECORRIVEL com ED vai para revisão manual
# em vez de reabrir este recurso — ver `_handle_embargos_interruption`.
_REOPENED_AGRAVO_AFTER_ED_RULE = PrazoRule(
    nome="Agravo de instrumento (reaberto após embargos de declaração)",
    categoria_trigger=CategoriaSemantica.DECISAO_RECORRIVEL,
    codigo_tpu=None,
    dias_uteis=15,
    tipo_acao=TipoAcao.RECORRER,
    base_legal="Art. 1.015 c/c Art. 1.026 CPC",
    # Reabertura do prazo recursal do agravo — mesma lógica da apelação
    # reaberta: não é prazo próprio, permanece elegível à dobra (admite_dobro
    # =True, o default).
)

# Prazo em dobro (arts. 180/183/186 CPC): base legal citada na anotação da regra
# quando a dobra é aplicada.
_DOBRO_BASE_LEGAL: dict[str, str] = {
    "fazenda": "art. 183 CPC",
    "mp": "art. 180 CPC",
    "defensoria": "art. 186 CPC",
}
_PARTES_REPRESENTADAS_VALIDAS = frozenset({"", "fazenda", "mp", "defensoria"})

# Categorias de decisão recorrível cujo prazo pode ser interrompido por
# embargos de declaração (art. 1.026 CPC). Usado para delimitar a janela de
# pareamento ED↔decisão em `_embargos_interruption_for`: a janela termina na
# próxima decisão recorrível de QUALQUER uma dessas categorias, não só da
# mesma — um processo tipicamente tem uma única SENTENCA mas pode ter várias
# DECISAO_RECORRIVEL, e uma sentença pode vir logo após uma interlocutória (ou
# vice-versa) sem que o ED de uma vaze para a outra.
_RECURSAVEL_CATEGORIAS = frozenset({CategoriaSemantica.SENTENCA, CategoriaSemantica.DECISAO_RECORRIVEL})


def _validate_parte_representada(parte_representada: str) -> None:
    if parte_representada not in _PARTES_REPRESENTADAS_VALIDAS:
        valores = sorted(_PARTES_REPRESENTADAS_VALIDAS)
        msg = f"parte_representada inválida: {parte_representada!r}; valores aceitos: {valores}"
        raise ValueError(msg)


def _rule_em_dobro(rule: PrazoRule, parte_representada: str) -> PrazoRule:
    """Anota a regra com o prazo em dobro (arts. 180/183/186 CPC) quando cabível.

    Aplicada por regra, nunca como multiplicador cego: só dobra quando
    ``parte_representada`` foi setada E ``rule.admite_dobro`` é True. ``compute_prazo``
    permanece intocado — recebe a regra já dobrada (ou a original, sem dobra).
    """
    if not parte_representada or not rule.admite_dobro:
        return rule
    return replace(
        rule,
        dias_uteis=rule.dias_uteis * 2,
        base_legal=f"{rule.base_legal} c/c {_DOBRO_BASE_LEGAL[parte_representada]} (em dobro)",
    )


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
    human reviews it. Common ``motivo`` values include ``data_ausente``,
    ``marco_legal_ausente`` and ``sem_regra_de_prazo``.
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


@dataclass(frozen=True, slots=True)
class _EmbargosInterruption:
    filing: AnalysisResult
    resolution: AnalysisResult | None


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
    data_inicio: date | None = None,
) -> Prazo:
    """Compute a single deadline from an analyzed movement + rule.

    Args:
        analysis: The analyzed movement result.
        rule: The applicable deadline rule.
        calendar: Judicial calendar for dias úteis computation.
        today: Override for current date (for testing).
        numero_cnj: Case number.
        data_inicio: Legal triggering date for the deadline, when it differs
            from the raw MNI movement timestamp.

    Returns:
        Computed Prazo with status.
    """
    today = today or date.today()

    # Invariant: undated movements are routed to revisao_manual upstream, never here.
    if analysis.data_hora is None:
        msg = "compute_prazo requires a dated movement; route undated to revisao_manual"
        raise ValueError(msg)

    # Start date: the legal triggering date. For simple publication/juntada
    # movements this is the movement date; for citation/intimation flows it may
    # be a later art. 231 CPC milestone. If the milestone cannot be identified,
    # do not silently use the raw MNI timestamp for a fatal prazo.
    data_inicio = data_inicio or _legal_start_date(analysis, calendar)
    if data_inicio is None:
        msg = "compute_prazo requires a legal start milestone; route ambiguous movement to revisao_manual"
        raise ValueError(msg)

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
    parte_representada: str = "",
) -> PrazoReport:
    """Compute all deadlines for a processo's analyzed movements.

    Args:
        numero_cnj: Case number.
        tribunal: Tribunal ID.
        analyses: List of analyzed movements.
        calendar: Judicial calendar (defaults to MG).
        today: Override current date (for testing).
        justica: "civel" or "trabalho".
        parte_representada: Ente representado para fins de prazo em dobro
            (arts. 180/183/186 CPC): "" (nenhum), "fazenda", "mp" ou
            "defensoria". Benefício exige intimação pessoal (arts. 180/183/186)
            e NÃO cobre prazos próprios (§§ 2º/4º) — configuração explícita do
            operador para o ente representado; nunca inferido dos autos. Art.
            229 não se aplica a autos eletrônicos (§2º) e não é modelado.

    Returns:
        PrazoReport with all computed deadlines.

    Raises:
        ValueError: If parte_representada is not one of the accepted values.
    """
    _validate_parte_representada(parte_representada)
    today = today or date.today()
    calendar = calendar or JudicialCalendar(uf=_tribunal_to_uf(tribunal))

    prazos: list[Prazo] = []
    revisao_manual: list[RevisaoManual] = []
    dated_analyses = [a for a in analyses if a.data_hora is not None]

    for analysis in analyses:
        if not analysis.requer_acao:
            continue

        # Missing/unparseable movement date: never fabricate a deadline from it.
        if analysis.data_hora is None:
            revisao_manual.append(
                RevisaoManual(analysis.movimento_id, analysis.categoria, "data_ausente", analysis.descricao)
            )
            continue

        # CPC art. 1.026: embargos de declaração interrompem o prazo recursal.
        # Não deixar o recurso original aparecer como VENCIDO enquanto os
        # embargos estiverem pendentes; ao julgamento, recalcular o prazo
        # recursal integral a partir da intimação. Acórdão/RE/REsp sem
        # categoria própria no CategoriaSemantica ficam fora do escopo — art.
        # 1.026 interrompe apenas prazos recursais (TipoAcao.RECORRER).
        if analysis.categoria == CategoriaSemantica.SENTENCA:
            handled = _handle_embargos_interruption(
                analysis,
                dated_analyses,
                calendar,
                today,
                numero_cnj,
                parte_representada,
                prazos,
                revisao_manual,
                reopened_rule=_REOPENED_APPEAL_AFTER_ED_RULE,
                reopened_suffix="reabertura-apelacao-ed",
                reopened_descricao=(
                    "Prazo de apelação reaberto após intimação do julgamento dos "
                    "embargos de declaração."
                ),
            )
            if handled:
                continue
        elif analysis.categoria == CategoriaSemantica.DECISAO_RECORRIVEL:
            # Escopo ESTREITO: só a interlocutória agravável (TPU 385) reabre
            # o agravo. Qualquer outra decisão recorrível (TPU 193/60/458/459
            # etc.) com ED detectados vai para revisão manual — nunca
            # fabricar recurso sem regra própria de reabertura.
            reopened_rule = _REOPENED_AGRAVO_AFTER_ED_RULE if analysis.codigo_tpu == 385 else None
            handled = _handle_embargos_interruption(
                analysis,
                dated_analyses,
                calendar,
                today,
                numero_cnj,
                parte_representada,
                prazos,
                revisao_manual,
                reopened_rule=reopened_rule,
                reopened_suffix="reabertura-agravo-ed",
                reopened_descricao=(
                    "Prazo de agravo de instrumento reaberto após intimação do "
                    "julgamento dos embargos de declaração."
                ),
            )
            if handled:
                continue

        # The ED filing/resolution movements are evidence of interruption/reopening,
        # not independent action items for this engine.
        if _is_embargos_declaracao_event(analysis):
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

        start_date = _legal_start_date(analysis, calendar)
        if start_date is None and _requires_explicit_legal_start(analysis):
            revisao_manual.append(
                RevisaoManual(
                    analysis.movimento_id,
                    analysis.categoria,
                    "marco_legal_ausente",
                    (
                        "Movimento de citação/intimação sem marco legal confiável "
                        "(juntada de AR/mandado/carta, confirmação eletrônica ou publicação DJe)."
                    ),
                )
            )
            continue

        for rule in rules:
            rule_efetiva = _rule_em_dobro(rule, parte_representada)
            prazo = compute_prazo(analysis, rule_efetiva, calendar, today, numero_cnj, data_inicio=start_date)
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
    """Extract UF from tribunal ID.

    Multi-state/national courts return ``"br"`` so they use only the federal
    holiday baseline instead of silently inheriting MG's state calendar.
    """
    normalized = tribunal_id.lower().strip()
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
        "trt1": "rj",
        "trt2": "sp",
        "trt3": "mg",
        "trt4": "rs",
        "trt5": "ba",
        "trt6": "pe",
        "trt7": "ce",
        "trt8": "pa",
        "trt9": "pr",
        "trt10": "df",
        "trt11": "am",
        "trt12": "sc",
        "trt13": "pb",
        "trt14": "ro",
        "trt15": "sp",
        "trt16": "ma",
        "trt17": "es",
        "trt18": "go",
        "trt19": "al",
        "trt20": "se",
        "trt21": "rn",
        "trt22": "pi",
        "trt23": "mt",
        "trt24": "ms",
        "trf6": "mg",
    }
    if normalized.startswith("trf") or normalized in {"tst", "stf", "stj"}:
        return _map.get(normalized, "br")
    return _map.get(normalized, "br")


def _requires_explicit_legal_start(analysis: AnalysisResult) -> bool:
    return analysis.categoria in {CategoriaSemantica.CITACAO, CategoriaSemantica.INTIMACAO}


def _legal_start_date(analysis: AnalysisResult, calendar: JudicialCalendar) -> date | None:
    """Return the legal prazo start milestone when it can be identified.

    CPC art. 231 makes citation/intimation deadlines depend on the concrete
    communication channel. If the MNI movement only says that a citation or
    intimation was issued, using ``dataHora`` is unsafe; callers should route it
    to manual review instead of fabricating a fatal deadline.
    """
    if analysis.data_hora is None:
        return None
    descricao = analysis.descricao or ""
    movement_date = analysis.data_hora.date()

    if _DJE_AVAILABILITY_RE.search(descricao):
        disponibilidade = _extract_date(descricao) or movement_date
        return calendar.next_dia_util(disponibilidade + timedelta(days=1))

    if _PUBLICATION_RE.search(descricao):
        return _extract_date(descricao) or movement_date

    if _JOINED_SERVICE_RE.search(descricao):
        return _extract_date(descricao) or movement_date

    if _ELECTRONIC_NOTICE_RE.search(descricao):
        return _extract_date(descricao) or movement_date

    if _COMPLETED_CITATION_RE.search(descricao):
        return _extract_date(descricao) or movement_date

    if not _requires_explicit_legal_start(analysis):
        return movement_date

    return None


def _extract_date(text: str) -> date | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        if match.group("iso_year"):
            return date(
                int(match.group("iso_year")),
                int(match.group("iso_month")),
                int(match.group("iso_day")),
            )
        year = int(match.group("br_year"))
        if year < 100:
            year += 2000
        return date(year, int(match.group("br_month")), int(match.group("br_day")))
    except ValueError:
        return None


def _is_embargos_declaracao_filing(analysis: AnalysisResult) -> bool:
    if _is_embargos_declaracao_resolution(analysis):
        return False
    return analysis.codigo_tpu == 199 or bool(_EMBARGOS_DECLARACAO_RE.search(analysis.descricao or ""))


def _is_embargos_declaracao_resolution(analysis: AnalysisResult) -> bool:
    descricao = analysis.descricao or ""
    if not _EMBARGOS_DECLARACAO_RE.search(descricao):
        return False
    if analysis.codigo_tpu in {463, 464, 465}:
        return True
    return bool(_EMBARGOS_RESOLUTION_RE.search(descricao))


def _is_embargos_declaracao_event(analysis: AnalysisResult) -> bool:
    return _is_embargos_declaracao_filing(analysis) or _is_embargos_declaracao_resolution(analysis)


def _movement_ordering_key(analysis: AnalysisResult) -> datetime:
    """Sort key over already-dated movements; callers pre-filter undated ones."""
    if analysis.data_hora is None:  # unreachable: lists are filtered before sorting
        msg = "movement without data_hora used as ordering key"
        raise ValueError(msg)
    return analysis.data_hora


def _embargos_interruption_for(
    decision: AnalysisResult,
    analyses: list[AnalysisResult],
) -> _EmbargosInterruption | None:
    """Pair a recursável decision with the embargos de declaração filed against it.

    Detection of the filing/resolution movements themselves (TPU 199/463-465 or
    regex on the descrição) is categoria-agnostic — an ED is always logged
    under ``CategoriaSemantica.RECURSO`` regardless of what it targets. The
    pairing is what needs to be window-bound: the ED filing considered must be
    posterior to ``decision`` and anterior to the next recursável decision —
    SENTENCA *or* DECISAO_RECORRIVEL, whichever comes first, not just another
    decision of the same categoria. A single ED after an interlocutória
    followed shortly by a sentença (or vice-versa) must pair with only one of
    them; bounding the window by same-categoria alone let it leak across
    categories, both falsely suppressing the other decision as interrompida
    and, once judged, fabricating a second reopened recurso for the same ED.
    Once the correct filing is identified, its resolution (julgamento) is
    searched within that SAME window — not unbounded. A julgamento published
    after the next recursável decision has already begun cannot be safely
    attributed to this decision's ED: it may in fact resolve the ED filed
    against that *next* decision instead. Since the windows of consecutive
    recursável decisions are disjoint by construction (each ends exactly
    where the next begins), bounding the resolution search the same way the
    filing search already is bounded means a given julgamento movement can
    ever match at most one decision's window — it can no longer be picked as
    "the" resolution for two different decisions simultaneously (the bug
    behind ``ed_julgamento_ambiguo``, see ``_ed_resolution_is_ambiguous``).
    When no resolution turns up inside the window, the caller correctly
    treats the ED as still pending rather than fabricating a mismatch.
    """
    if decision.data_hora is None:
        return None
    decision_dt = decision.data_hora
    after_decision = [
        analysis for analysis in analyses if analysis.data_hora is not None and analysis.data_hora > decision_dt
    ]
    next_recursavel_dates = [
        analysis.data_hora
        for analysis in after_decision
        if analysis.data_hora is not None and analysis.categoria in _RECURSAVEL_CATEGORIAS
    ]
    window_end = min(next_recursavel_dates) if next_recursavel_dates else None
    window = [
        analysis
        for analysis in after_decision
        if window_end is None or (analysis.data_hora is not None and analysis.data_hora < window_end)
    ]
    filings = [analysis for analysis in window if _is_embargos_declaracao_filing(analysis)]
    if not filings:
        return None
    filing = min(filings, key=_movement_ordering_key)
    filing_dt = filing.data_hora
    if filing_dt is None:  # unreachable: window already excludes undated movements
        return None
    resolutions = [
        analysis
        for analysis in window
        if analysis.data_hora is not None
        and analysis.data_hora > filing_dt
        and _is_embargos_declaracao_resolution(analysis)
    ]
    resolution = min(resolutions, key=_movement_ordering_key) if resolutions else None
    return _EmbargosInterruption(filing=filing, resolution=resolution)


def _ed_resolution_is_ambiguous(
    decision: AnalysisResult,
    resolution_dt: datetime,
    analyses: list[AnalysisResult],
) -> bool:
    """Whether ``resolution_dt`` cannot be safely attributed to ``decision`` alone.

    Bounding the resolution search to the decision's own window (see
    ``_embargos_interruption_for``) already prevents the SAME julgamento
    movement from being paired with two different decisions. But that
    heuristic window boundary — "the next recursável decision" — is only a
    proxy for how the tribunal actually grouped its rulings; it is not a
    textual link between a julgamento and the specific ED it resolves. When,
    at the moment this candidate julgamento appears, some OTHER recursável
    decision in the processo also has an ED that was filed earlier and is
    still unresolved, a single combined julgamento covering both pending EDs
    is a realistic possibility the window cannot rule out. Rather than guess,
    both stay unresolved for automated purposes: this decision is routed to
    ``RevisaoManual`` (motivo ``ed_julgamento_ambiguo``) instead of reopening.

    A decision is the ONLY one with an outstanding ED at ``resolution_dt``
    (nothing else pending) is unambiguous and reopens normally.
    """
    for other in analyses:
        if other.movimento_id == decision.movimento_id or other.categoria not in _RECURSAVEL_CATEGORIAS:
            continue
        other_interruption = _embargos_interruption_for(other, analyses)
        if other_interruption is None:
            continue
        other_filing_dt = other_interruption.filing.data_hora
        if other_filing_dt is None or other_filing_dt >= resolution_dt:
            continue
        other_resolution = other_interruption.resolution
        if (
            other_resolution is not None
            and other_resolution.data_hora is not None
            and other_resolution.data_hora < resolution_dt
        ):
            continue  # other decision already paired with its own earlier, disjoint julgamento
        return True
    return False


def _handle_embargos_interruption(
    analysis: AnalysisResult,
    dated_analyses: list[AnalysisResult],
    calendar: JudicialCalendar,
    today: date,
    numero_cnj: str,
    parte_representada: str,
    prazos: list[Prazo],
    revisao_manual: list[RevisaoManual],
    *,
    reopened_rule: PrazoRule | None,
    reopened_suffix: str,
    reopened_descricao: str,
) -> bool:
    """Detect and handle a CPC art. 1.026 embargos-de-declaração interruption.

    Applies to SENTENCA (apelação) and to DECISAO_RECORRIVEL decisions whose
    TPU code maps to a known reopening rule (currently only TPU 385 —
    interlocutória agravável, art. 1.015 CPC). Acórdão/RE/REsp sem categoria
    própria no CategoriaSemantica — fora do escopo; art. 1.026 interrompe
    apenas prazos recursais.

    When ``reopened_rule`` is None, this decision has no known recursal rule
    to reopen: embargos detected against it are suppressed and routed to
    manual review instead of risking a fabricated recurso.

    When a julgamento is found but ``_ed_resolution_is_ambiguous`` flags it
    (another decision's ED is also outstanding at that moment), the decision
    is likewise routed to manual review (motivo ``ed_julgamento_ambiguo``)
    instead of reopening — a julgamento is never used to reopen two
    different recursos, and never guessed onto one when it might belong to
    another (art. 1.026 CPC; regra de ouro: na dúvida, revisão manual).

    Returns:
        True when embargos de declaração were detected against ``analysis``
        — the caller should skip normal rule-matching for this movement,
        since the deadline was suppressed, routed to manual review, or
        reopened as a new ``Prazo``. False when no embargos were filed, so
        normal rule-matching should proceed.
    """
    interruption = _embargos_interruption_for(analysis, dated_analyses)
    if interruption is None:
        return False

    if reopened_rule is None:
        revisao_manual.append(
            RevisaoManual(
                analysis.movimento_id,
                analysis.categoria,
                "ed_sobre_decisao_recurso_incerto",
                (
                    "Embargos de declaração opostos contra decisão sem regra de "
                    "reabertura de recurso conhecida; revise manualmente o prazo "
                    "recursal aplicável (art. 1.026 CPC)."
                ),
            )
        )
        return True

    if interruption.resolution is None:
        revisao_manual.append(
            RevisaoManual(
                analysis.movimento_id,
                analysis.categoria,
                "prazo_interrompido_embargos_pendentes",
                (
                    "Prazo recursal interrompido por embargos de declaração; "
                    "aguarde/registre a publicação do julgamento dos embargos."
                ),
            )
        )
        return True

    resolution = interruption.resolution
    resolution_dt = resolution.data_hora
    if resolution_dt is not None and _ed_resolution_is_ambiguous(analysis, resolution_dt, dated_analyses):
        revisao_manual.append(
            RevisaoManual(
                analysis.movimento_id,
                analysis.categoria,
                "ed_julgamento_ambiguo",
                (
                    "Julgamento de embargos de declaração não pôde ser atribuído com "
                    "segurança a esta decisão; confira qual ED foi julgado (art. 1.026 CPC)."
                ),
            )
        )
        return True

    # CPC art. 1.003 §5º c/c art. 1.026: the reopened period runs from the
    # intimação of the ED judgment, not the raw judgment timestamp. Reuse the
    # same marco-legal logic so a DJe/publicação date carried by the
    # resolution movement is honoured; fall back to the resolution date when
    # the movement gives no explicit milestone.
    reopened_start = _legal_start_date(resolution, calendar)
    reopened = replace(
        analysis,
        movimento_id=f"{analysis.movimento_id}:{reopened_suffix}",
        data_hora=resolution.data_hora,
        descricao=reopened_descricao,
    )
    reopened_rule_efetiva = _rule_em_dobro(reopened_rule, parte_representada)
    prazos.append(
        compute_prazo(
            reopened,
            reopened_rule_efetiva,
            calendar,
            today,
            numero_cnj,
            data_inicio=reopened_start,
        )
    )
    return True
