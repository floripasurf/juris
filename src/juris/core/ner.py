"""Legal NER redactor (LeNER-Br) — the free-text name layer of de-id (ADR-0016).

The structured de-id (core/deid) handles CPF/CNPJ/CNJ/OAB; this adds the missing
piece: party/person and organisation names. Backed by a LeNER-Br model (a
HuggingFace token-classification pipeline, loaded lazily), it returns the entity
spans to redact, plugging into ``deidentify(..., ner_redactor=...)``. With it, the
de-id is *complete* and the cloud gate can fail closed (allow_partial=False).

The pipeline is injectable so the logic is unit-tested without the heavy model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from juris.core.observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)

# LeNER-Br entity types that are PII for de-identification purposes.
_PII_LABELS = frozenset({"PESSOA", "ORGANIZACAO", "PER", "ORG", "PERSON"})


class LegalNER:
    """Extracts PII entity spans (names, organisations) from legal text."""

    DEFAULT_MODEL = "pierreguillou/ner-bert-base-cased-pt-lenerbr"  # noqa: S105 — model id, not a secret

    def __init__(
        self,
        *,
        pipeline: Callable[[str], list[dict[str, Any]]] | None = None,
        model: str = DEFAULT_MODEL,
        labels: frozenset[str] = _PII_LABELS,
    ) -> None:
        self._pipeline = pipeline
        self._model = model
        self._labels = labels

    def _get_pipeline(self) -> Callable[[str], list[dict[str, Any]]]:
        if self._pipeline is None:
            logger.info("ner_model_loading", model=self._model)
            try:
                from transformers import pipeline as hf_pipeline

                self._pipeline = hf_pipeline(
                    "token-classification", model=self._model, aggregation_strategy="simple"
                )
            except Exception as exc:
                msg = (
                    f"Modelo NER de de-id ({self._model}) indisponível: {exc}. "
                    "Pré-baixe-o (ver onboarding §3.5) ou desligue o NER "
                    "(cloud_safe_llm require_ner=False) — sem ele o caminho cloud "
                    "falha fechado para não vazar nomes."
                )
                raise RuntimeError(msg) from exc
        return self._pipeline

    def _is_pii(self, entity: dict[str, Any]) -> bool:
        group = str(entity.get("entity_group") or entity.get("entity") or "").upper()
        return group in self._labels

    def redact_entities(self, text: str) -> list[str]:
        """Return the PII spans (deduped, longest first) to redact from ``text``."""
        results = self._get_pipeline()(text)
        spans = {str(e.get("word", "")).strip() for e in results if self._is_pii(e)}
        # Longest first so a full name is replaced before its first-name substring.
        return sorted((s for s in spans if s), key=len, reverse=True)
