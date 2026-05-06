"""Ingester for OAB seccional petition templates.

GATED: Requires manual URL curation in data/oab_modelos_index.json by a lawyer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)
_DEFAULT_INDEX = Path(__file__).resolve().parents[4] / "data" / "oab_modelos_index.json"


class OABModelosIngester(CorpusIngester):
    """Ingests OAB seccional petition templates from curated URLs.

    Rate limit: ≤1 req/2sec, respects robots.txt.
    Target seccionais: OAB-SP, OAB-RJ, OAB-MG, OAB-RS, OAB Federal.

    Args:
        index_path: Path to the JSON index of curated URLs.
        limit: Maximum number of entries to ingest (None for all).
    """

    def __init__(
        self,
        index_path: Path | None = None,
        limit: int | None = None,
    ) -> None:
        self._index_path = index_path or _DEFAULT_INDEX
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Read curated OAB template URLs and fetch content.

        Returns:
            List of FonteJurisprudencia, empty until URLs are curated.
        """
        if not self._index_path.exists():
            logger.warning("OAB index not found: %s", self._index_path)
            return []

        with self._index_path.open(encoding="utf-8") as f:
            entries = json.load(f)

        if not entries:
            logger.info("OAB index is empty — awaiting manual URL curation")
            return []

        # TODO: Implement HTTP fetching once URLs are curated
        logger.info(
            "OAB index has %d entries — HTTP fetching not yet implemented",
            len(entries),
        )
        return []

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks.
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)
