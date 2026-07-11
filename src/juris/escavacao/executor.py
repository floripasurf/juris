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

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from juris.core.observability import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from juris.escavacao.queue import AlvoEscavacao

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InteiroTeor:
    """One scraped full-text decision, with provenance for the deep corpus."""

    numero_cnj: str
    texto: str
    fonte: str  # provider that supplied it
    origem_tema: str  # espinha id that surfaced this case
    parcial: bool = False  # True = procedural trail (DataJud), not the full acórdão
    url: str | None = None  # where it came from (provenance)
    licenca: str | None = None  # source terms/licence (e.g. "dados públicos TST")
    data_coleta: str | None = None  # ISO date the fetcher collected it
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """SHA-256 of the full text — identity for dedup + provenance."""
        return hashlib.sha256(self.texto.encode("utf-8")).hexdigest()

    @property
    def dedup_key(self) -> tuple[str, str, str]:
        """Dedup by (content, processo, source) — re-collection is idempotent, but
        the same decision from a *different* source is kept (corroboration)."""
        return (self.content_hash, self.numero_cnj, self.fonte)


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


def _to_fonte(it: InteiroTeor) -> Any:
    """Map a harvested full text onto a corpus source for chunking/retrieval."""
    from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte

    tribunal = str(it.metadata.get("tribunal") or it.fonte).upper()
    ementa = str(it.metadata.get("ementa") or it.texto[:500])
    return FonteJurisprudencia(
        id=f"escavacao_{it.fonte}_{it.content_hash[:16]}",
        tribunal=tribunal,
        tipo=TipoFonte.ACORDAO_PUBLICADO,
        numero=it.numero_cnj,
        ementa=ementa,
        texto_integral=it.texto,
        temas=[it.origem_tema] if it.origem_tema else [],
        situacao="vigente",
        hierarquia=5,
        source_url=it.url,
    )


def ingest_inteiro_teor(coletados: list[InteiroTeor], store: Any) -> int:
    """Bridge the escavação output INTO the searchable corpus (closes the dead-end).

    Each full acórdão is mapped to a corpus source, chunked, and upserted into
    ``store`` (embeddings are placeholders for the FTS store). Partial trails
    (``parcial=True``, DataJud movements) are skipped — they aren't real decisions and
    would pollute retrieval. Returns the number of chunks ingested.
    """
    from juris.repertory.chunking import chunk_fonte

    total = 0
    for it in coletados:
        if it.parcial:
            continue
        chunks = chunk_fonte(_to_fonte(it))
        store.upsert(chunks, [[] for _ in chunks])
        total += len(chunks)
    return total


def write_inteiro_teor(coletados: list[InteiroTeor], out_dir: Path) -> list[Path]:
    """Write each harvested full text as one JSON file (the engine then ingests).

    Returns the written paths. The directory is created if needed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for teor in coletados:
        safe_cnj = re.sub(r"[^0-9A-Za-z]", "_", teor.numero_cnj)
        safe_fonte = re.sub(r"[^0-9A-Za-z]", "_", teor.fonte)
        # name encodes the dedup identity (cnj + fonte + content hash) so the same
        # processo from TST and DataJud are kept as distinct files, never overwritten.
        path = out_dir / f"{safe_cnj}__{safe_fonte}__{teor.content_hash[:12]}.json"
        path.write_text(
            json.dumps(
                {
                    "numero_cnj": teor.numero_cnj,
                    "texto": teor.texto,
                    "fonte": teor.fonte,
                    "origem_tema": teor.origem_tema,
                    "parcial": teor.parcial,
                    "url": teor.url,
                    "licenca": teor.licenca,
                    "data_coleta": teor.data_coleta,
                    "content_hash": teor.content_hash,
                    "metadata": teor.metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        written.append(path)
    return written


def load_inteiro_teor(out_dir: Path) -> list[InteiroTeor]:
    """Read back the JSONs written by :func:`write_inteiro_teor` (ingestion feed)."""
    loaded: list[InteiroTeor] = []
    for path in sorted(out_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded.append(
            InteiroTeor(
                numero_cnj=data["numero_cnj"],
                texto=data["texto"],
                fonte=data["fonte"],
                origem_tema=data["origem_tema"],
                parcial=data.get("parcial", False),
                url=data.get("url"),
                licenca=data.get("licenca"),
                data_coleta=data.get("data_coleta"),
                metadata=data.get("metadata", {}),
            )
        )
    return loaded


def dedup_inteiro_teor(teores: list[InteiroTeor]) -> list[InteiroTeor]:
    """Drop re-collected duplicates by :attr:`InteiroTeor.dedup_key`.

    The same decision from a *different* source is kept — corroboration is a
    ranking signal, not noise.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[InteiroTeor] = []
    for teor in teores:
        if teor.dedup_key in seen:
            continue
        seen.add(teor.dedup_key)
        unique.append(teor)
    return unique
