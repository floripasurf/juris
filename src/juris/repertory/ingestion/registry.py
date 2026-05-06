"""Ingester registry for corpus source dispatch.

Maps source keys to their seed files and metadata,
enabling selective or bulk ingestion via CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from juris.repertory.corpus.models import TipoFonte
from juris.repertory.corpus.status import is_active
from juris.repertory.ingestion.base import IngestionResult
from juris.repertory.ingestion.seed_loader import SeedLoader

if TYPE_CHECKING:
    from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngesterEntry:
    """Registry entry for a corpus source.

    Args:
        key: Short identifier (e.g., "stf-sv").
        label: Human-readable name.
        seed_file: Filename in data/corpus/.
        tipo: TipoFonte enum value.
        tribunal: Court identifier.
        hierarquia: Hierarchy level (1-7).
        ingester_class: Optional class-based ingester (instead of SeedLoader).
        source_dir: Optional source directory for class-based ingesters.
    """

    key: str
    label: str
    seed_file: str
    tipo: TipoFonte
    tribunal: str
    hierarquia: int
    ingester_class: type | None = None
    source_dir: str | None = None


_sv = IngesterEntry
REGISTRY: dict[str, IngesterEntry] = {
    "stf-sv": _sv(
        "stf-sv", "STF Súmulas Vinculantes",
        "sumulas_vinculantes.json", TipoFonte.SUMULA_VINCULANTE, "STF", 1,
    ),
    "stf-rg": _sv(
        "stf-rg", "STF Repercussão Geral",
        "temas_repercussao_geral_stf.json", TipoFonte.RE_STF, "STF", 2,
    ),
    "stj-repetitivos": _sv(
        "stj-repetitivos", "STJ Repetitivos",
        "temas_repetitivos_stj.json", TipoFonte.RESP_REPETITIVO, "STJ", 3,
    ),
    "stf-sumulas": _sv(
        "stf-sumulas", "STF Súmulas",
        "sumulas_stf.json", TipoFonte.SUMULA, "STF", 4,
    ),
    "stj-sumulas": _sv(
        "stj-sumulas", "STJ Súmulas",
        "sumulas_stj.json", TipoFonte.SUMULA, "STJ", 4,
    ),
    "tst-sumulas": _sv(
        "tst-sumulas", "TST Súmulas",
        "sumulas_tst.json", TipoFonte.SUMULA, "TST", 4,
    ),
    "tst-ojs": _sv(
        "tst-ojs", "TST OJs",
        "ojs_tst.json", TipoFonte.JURISPRUDENCIA_UNIFORME, "TST", 5,
    ),
    "tjdft-modelos": _sv(
        "tjdft-modelos", "TJDFT Modelos de Petição",
        "", TipoFonte.MODELO_PETICAO, "TJDFT", 7,
        ingester_class=None,
        source_dir="Petiçoes",
    ),
    "stf-landmark": _sv(
        "stf-landmark", "STF Casos Relevantes (Landmark)",
        "", TipoFonte.ACORDAO_LANDMARK, "STF", 3,
        ingester_class=None,
        source_dir="STF_Casos_Relevantes",
    ),
    "stf-informativos": _sv(
        "stf-informativos", "STF Informativos",
        "", TipoFonte.NOTICIA_TRIBUNAL, "STF", 7,
        ingester_class=None,
        source_dir="STF_Casos_Relevantes/Informativos",
    ),
}


def get_available_sources() -> list[IngesterEntry]:
    """Return all registered sources sorted by hierarchy.

    Returns:
        List of IngesterEntry sorted by hierarquia.
    """
    return sorted(REGISTRY.values(), key=lambda e: (e.hierarquia, e.key))


def _get_class_ingester(
    entry: IngesterEntry,
    project_root: Path,
    limit: int | None = None,
) -> CorpusIngester | None:
    """Resolve a class-based ingester for the given entry.

    Args:
        entry: Registry entry.
        project_root: Project root directory.
        limit: Max items to ingest.

    Returns:
        CorpusIngester instance, or None if seed-based.
    """

    if entry.key == "tjdft-modelos":
        from juris.repertory.ingestion.tjdft_modelos import TJDFTModelosIngester

        source_dir = project_root / (entry.source_dir or "Petiçoes")
        return TJDFTModelosIngester(source_dir=source_dir, limit=limit)

    if entry.key == "stf-landmark":
        from juris.repertory.ingestion.stf_landmark import STFLandmarkIngester

        source_dir = project_root / (entry.source_dir or "STF_Casos_Relevantes")
        return STFLandmarkIngester(source_dir=source_dir, limit=limit)

    if entry.key == "stf-informativos":
        from juris.repertory.ingestion.stf_informativos import STFInformativosIngester

        source_dir = project_root / (entry.source_dir or "STF_Casos_Relevantes/Informativos")
        return STFInformativosIngester(source_dir=source_dir, limit=limit)

    return None


def ingest_source(
    key: str,
    corpus_dir: Path,
    store: object,
    embedder: object | None = None,
    include_superseded: bool = False,
    limit: int | None = None,
) -> IngestionResult:
    """Ingest a single source by key.

    Args:
        key: Source key from REGISTRY.
        corpus_dir: Path to the corpus directory.
        store: VectorStore instance.
        embedder: Optional embedder.
        include_superseded: Include non-vigente entries.
        limit: Maximum number of items to ingest (for class-based ingesters).

    Returns:
        IngestionResult with counts.

    Raises:
        KeyError: If key is not in REGISTRY.
    """
    if key not in REGISTRY:
        msg = f"Unknown source key: {key}. Available: {', '.join(REGISTRY)}"
        raise KeyError(msg)

    entry = REGISTRY[key]
    project_root = corpus_dir.parent if corpus_dir.name == "corpus" else corpus_dir.parent

    # Try class-based ingester first
    ingester = _get_class_ingester(entry, project_root, limit=limit)
    if ingester is not None:
        return _run_class_ingester(ingester, store, embedder)

    loader = SeedLoader(corpus_dir=corpus_dir, include_superseded=include_superseded)
    return loader.ingest(store, embedder)  # type: ignore[arg-type]


def _run_class_ingester(
    ingester: object,
    store: object,
    embedder: object | None = None,
) -> IngestionResult:
    """Run a class-based ingester through the standard pipeline.

    Args:
        ingester: CorpusIngester instance.
        store: VectorStore instance.
        embedder: Optional embedder.

    Returns:
        IngestionResult with counts.
    """
    from juris.repertory.chunking import DocumentChunk

    fontes = ingester.fetch()  # type: ignore[union-attr]
    all_chunks: list[DocumentChunk] = []
    for fonte in fontes:
        all_chunks.extend(ingester.parse(fonte))  # type: ignore[union-attr]

    if not all_chunks:
        return IngestionResult(
            total_fetched=len(fontes), total_chunks=0, total_embedded=0,
        )

    # Store chunks
    texts = [c.text for c in all_chunks]
    if embedder is not None:
        embeddings = embedder.embed_texts(texts)  # type: ignore[union-attr]
        stored = store.upsert(all_chunks, embeddings)  # type: ignore[union-attr]
    else:
        dim = getattr(embedder, "dimension", 1024) if embedder else 1024
        zero_embeddings = [[0.0] * dim for _ in all_chunks]
        stored = store.upsert(all_chunks, zero_embeddings)  # type: ignore[union-attr]

    logger.info(
        "Ingested %d fontes -> %d chunks -> %d stored (class-based)",
        len(fontes), len(all_chunks), stored,
    )

    return IngestionResult(
        total_fetched=len(fontes),
        total_chunks=len(all_chunks),
        total_embedded=stored,
    )


def ingest_all(
    corpus_dir: Path,
    store: object,
    embedder: object | None = None,
    include_superseded: bool = False,
) -> dict[str, IngestionResult]:
    """Ingest all registered sources.

    Args:
        corpus_dir: Path to the corpus directory.
        store: VectorStore instance.
        embedder: Optional embedder.
        include_superseded: Include non-vigente entries.

    Returns:
        Dict mapping source key to IngestionResult.
    """
    loader = SeedLoader(corpus_dir=corpus_dir, include_superseded=include_superseded)
    result = loader.ingest(store, embedder)  # type: ignore[arg-type]
    return {"all": result}


def count_source_entries(corpus_dir: Path, include_superseded: bool = False) -> dict[str, int]:
    """Count entries per source file.

    Args:
        corpus_dir: Path to the corpus directory.
        include_superseded: Include non-vigente entries.

    Returns:
        Dict mapping source key to entry count.
    """
    import json

    counts: dict[str, int] = {}
    for key, entry in REGISTRY.items():
        if not entry.seed_file:
            # Class-based ingester — skip seed counting
            counts[key] = 0
            continue
        filepath = corpus_dir / entry.seed_file
        if not filepath.exists():
            counts[key] = 0
            continue
        with filepath.open(encoding="utf-8") as f:
            data = json.load(f)
        if include_superseded:
            counts[key] = len(data)
        else:
            counts[key] = sum(
                1 for d in data
                if is_active(entry.tipo, d.get("situacao", "vigente"))
            )
    return counts
