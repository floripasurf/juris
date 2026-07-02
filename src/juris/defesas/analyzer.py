"""Defense analysis orchestrator — rule-first, LLM only for ambiguous cases."""

from __future__ import annotations

from typing import Any

from juris.core.observability import get_logger
from juris.defesas.context import ProcessoContext
from juris.defesas.decadencia import verificar_decadencia
from juris.defesas.models import DefesaReport, ResultadoDefesa, TipoDefesa
from juris.defesas.preclusao import verificar_preclusao
from juris.defesas.preliminares import identificar_preliminares
from juris.defesas.prescricao import verificar_prescricao
from juris.defesas.prescricao_intercorrente import verificar_prescricao_intercorrente
from juris.defesas.registry import codigo_for_context, institutos_for_context

logger = get_logger(__name__)


class DefesaAnalyzer:
    """Orchestrates all defense checks for a processo.

    Strategy (rule-first):
    1. Run all deterministic checks (prescricao, decadencia, preclusao, preliminares).
    2. Only call LLM for ambiguous tipo_acao identification.
    3. Aggregate results into DefesaReport.
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    async def analyze(self, context: ProcessoContext) -> DefesaReport:
        """Run full defense analysis on a processo.

        Args:
            context: ProcessoContext with all case data.

        Returns:
            DefesaReport with all identified defenses.
        """
        defesas: list[ResultadoDefesa] = []
        codigo_catalogo = codigo_for_context(context)
        catalogo = institutos_for_context(context)

        # 1. Prescricao check
        defesas.extend(await self._check_prescricao(context))

        # 2. Prescricao intercorrente
        defesas.extend(self._check_prescricao_intercorrente(context))

        # 3. Decadencia
        defesas.extend(await self._check_decadencia(context))

        # 4. Preclusao (all three types)
        defesas.extend(self._check_preclusao(context))

        # 5. Preliminares (Art. 337 CPC)
        defesas.extend(identificar_preliminares(context))

        # Filter to applicable or high-confidence results
        aplicaveis = [d for d in defesas if d.aplicavel]
        nao_aplicaveis = [d for d in defesas if not d.aplicavel and d.confianca >= 0.5]

        todas = aplicaveis + nao_aplicaveis

        summary = self._build_summary(
            context.numero_cnj,
            aplicaveis,
            codigo_catalogo.value,
            len(catalogo),
        )

        logger.info(
            "defesa_analysis_complete",
            numero_cnj=context.numero_cnj,
            total_checks=len(defesas),
            aplicaveis=len(aplicaveis),
            codigo_catalogo=codigo_catalogo.value,
            catalogo_institutos=len(catalogo),
        )

        return DefesaReport(
            numero_cnj=context.numero_cnj,
            defesas_identificadas=todas,
            codigos_consultados=[codigo_catalogo.value],
            institutos_consultados=[inst.nome for inst in catalogo],
            summary=summary,
        )

    async def _check_prescricao(self, context: ProcessoContext) -> list[ResultadoDefesa]:
        """Check prescription based on context data."""
        results: list[ResultadoDefesa] = []

        if context.data_fato_gerador and context.data_ajuizamento:
            # Try to determine tipo_acao from classe/assuntos
            tipo_acao = self._infer_tipo_acao(context)
            if tipo_acao:
                result = verificar_prescricao(
                    tipo_acao=tipo_acao,
                    data_fato=context.data_fato_gerador,
                    data_ajuizamento=context.data_ajuizamento,
                )
                results.append(result)
            elif self._llm is not None:
                # Use LLM to identify tipo_acao
                inferred = await self._llm_infer_tipo_acao(context)
                if inferred:
                    result = verificar_prescricao(
                        tipo_acao=inferred,
                        data_fato=context.data_fato_gerador,
                        data_ajuizamento=context.data_ajuizamento,
                    )
                    results.append(result)

        return results

    def _check_prescricao_intercorrente(self, context: ProcessoContext) -> list[ResultadoDefesa]:
        """Check intercurrent prescription from movement data."""
        results: list[ResultadoDefesa] = []

        # Look for execution-phase suspension
        if context.fase_atual and "execu" in context.fase_atual.lower() and context.movimentos:
            # Find the last meaningful act date
            last_mov = context.movimentos[-1]
            data_str = last_mov.get("data", "") if isinstance(last_mov, dict) else ""
            if data_str:
                from datetime import date

                try:
                    parts = data_str.split("-")
                    data_ultimo_ato = date(int(parts[0]), int(parts[1]), int(parts[2][:2]))
                    result = verificar_prescricao_intercorrente(
                        data_ultimo_ato=data_ultimo_ato,
                        data_suspensao=None,
                        prazo_original_anos=3,  # default, should be inferred
                    )
                    results.append(result)
                except (ValueError, IndexError):
                    pass

        return results

    async def _check_decadencia(self, context: ProcessoContext) -> list[ResultadoDefesa]:
        """Check decadence for CDC and other applicable cases."""
        results: list[ResultadoDefesa] = []

        # Check for CDC-related assuntos
        assuntos_lower = [a.lower() for a in context.assuntos]
        cdc_keywords = ["consumidor", "cdc", "vicio", "produto", "servico"]

        is_cdc = any(kw in assunto for assunto in assuntos_lower for kw in cdc_keywords)

        if is_cdc and context.data_fato_gerador:
            for tipo in ["cdc vicio duravel", "cdc vicio nao duravel"]:
                result = verificar_decadencia(
                    tipo_direito=tipo,
                    data_ciencia=context.data_fato_gerador,
                    data_exercicio=context.data_ajuizamento,
                )
                results.append(result)

        return results

    def _check_preclusao(self, context: ProcessoContext) -> list[ResultadoDefesa]:
        """Check all three types of preclusion."""
        results: list[ResultadoDefesa] = []

        for tipo in [
            TipoDefesa.PRECLUSAO_TEMPORAL,
            TipoDefesa.PRECLUSAO_CONSUMATIVA,
            TipoDefesa.PRECLUSAO_LOGICA,
        ]:
            result = verificar_preclusao(
                tipo=tipo,
                movimentos=context.movimentos,
            )
            results.append(result)

        return results

    def _infer_tipo_acao(self, context: ProcessoContext) -> str | None:
        """Infer action type from classe and assuntos (rule-based)."""
        classe = (context.classe or "").lower()
        assuntos = [a.lower() for a in context.assuntos]
        all_text = classe + " " + " ".join(assuntos)

        # Map common classes/assuntos to tipo_acao
        mappings: list[tuple[list[str], str]] = [
            (["indeniza", "dano", "reparacao"], "Indenizatoria"),
            (["cobranca", "titulo", "cambial"], "Cobranca"),
            (["alimento", "pensao"], "Alimentos"),
            (["aluguel", "locacao", "despejo"], "Cobranca de alugueis"),
            (["consumidor", "cdc"], "CDC fato do produto"),
            (["trabalhista", "reclamacao"], "Trabalhista bienal"),
            (["possessoria", "reintegracao", "esbulho"], "Pretensao possessoria"),
            (["seguro"], "Seguro"),
            (["contrato", "inadimplemento"], "Responsabilidade contratual"),
            (["enriquecimento"], "Enriquecimento sem causa"),
        ]

        for keywords, tipo in mappings:
            if any(kw in all_text for kw in keywords):
                return tipo

        return None

    async def _llm_infer_tipo_acao(self, context: ProcessoContext) -> str | None:
        """Use LLM to infer action type when rules are ambiguous."""
        if self._llm is None:
            return None

        try:
            prompt = (
                f"Classe processual: {context.classe}\n"
                f"Assuntos: {', '.join(context.assuntos)}\n"
                f"Ramo: {context.ramo_justica}\n\n"
                "Qual o tipo de acao para fins de prescricao? "
                "Responda apenas com o tipo (ex: Indenizatoria, Cobranca, etc)."
            )
            response = await self._llm.complete(prompt=prompt, temperature=0.0)
            return response.text.strip() if response and response.text else None
        except Exception:  # noqa: BLE001
            logger.warning("llm_infer_tipo_acao_failed", numero_cnj=context.numero_cnj)
            return None

    def _build_summary(
        self,
        numero_cnj: str,
        aplicaveis: list[ResultadoDefesa],
        codigo_catalogo: str,
        total_institutos: int,
    ) -> str:
        """Build a human-readable summary."""
        catalog_note = f" Catálogo consultado: {codigo_catalogo} ({total_institutos} instituto(s))."
        if not aplicaveis:
            return f"{numero_cnj}: nenhuma defesa processual identificada automaticamente.{catalog_note}"

        tipos = [d.tipo.value for d in aplicaveis]
        return f"{numero_cnj}: {len(aplicaveis)} defesa(s) identificada(s): {', '.join(tipos)}.{catalog_note}"
