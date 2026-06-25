"""Escavação executor — drives the directed-scraping queue to full text.

Takes the prioritised :class:`AlvoEscavacao` queue (SCHEMA §4) and an injected
:class:`EscavacaoFetcher` (the Source Mesh adapter — DataJud / esaj / MNI), and
fetches the inteiro teor of each leading case. This is where the *moat* is filled:
the espinha tells us *which* cases to dig; the executor digs them.

Sequential by design (gentle on rate-limited / gated sources). Per-target
failures are isolated and recorded — one unreachable provider never sinks the
batch. Persistence of the :class:`InteiroTeor` into the deep corpus is the
caller's concern (kept out of this orchestration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from juris.core.observability import get_logger

if TYPE_CHECKING:
    from juris.escavacao.queue import AlvoEscavacao

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InteiroTeor:
    """One scraped full-text decision."""

    numero_cnj: str
    texto: str
    fonte: str  # provider that supplied it
    origem_tema: str  # espinha id that surfaced this case
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EscavacaoResult:
    """Outcome of an escavação run."""

    coletados: list[InteiroTeor]
    falhas: list[str]  # CNJs that couldn't be fetched
    pulados: int = 0  # targets left out by max_alvos


class EscavacaoFetcher(Protocol):
    """Fetches the inteiro teor for one target (a Source Mesh adapter)."""

    async def fetch(self, alvo: AlvoEscavacao) -> InteiroTeor | None: ...


async def executar_escavacao(
    fila: list[AlvoEscavacao],
    fetcher: EscavacaoFetcher,
    *,
    max_alvos: int | None = None,
) -> EscavacaoResult:
    """Fetch the inteiro teor for each target in the prioritised queue.

    Args:
        fila: The prioritised escavação queue (highest-authority origin first).
        fetcher: The Source Mesh adapter that retrieves full text by CNJ.
        max_alvos: Optional per-run cap (the rest are counted as ``pulados``).

    Returns:
        :class:`EscavacaoResult` with the collected full texts and the failures.
    """
    alvos = fila[:max_alvos] if max_alvos is not None else fila
    coletados: list[InteiroTeor] = []
    falhas: list[str] = []

    for alvo in alvos:
        try:
            teor = await fetcher.fetch(alvo)
        except Exception:  # noqa: BLE001 — one bad provider must not sink the batch
            logger.warning("escavacao_fetch_error", numero_cnj=alvo.numero_cnj)
            teor = None
        if teor is not None:
            coletados.append(teor)
        else:
            falhas.append(alvo.numero_cnj)

    logger.info(
        "escavacao_run",
        coletados=len(coletados),
        falhas=len(falhas),
        pulados=len(fila) - len(alvos),
    )
    return EscavacaoResult(coletados=coletados, falhas=falhas, pulados=len(fila) - len(alvos))
