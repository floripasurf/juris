"""Base classes for corpus ingestion pipelines.

Defines the abstract interface for fetching, parsing, and ingesting
jurisprudence sources into the vector store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import FonteJurisprudencia


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result of an ingestion operation.

    Args:
        total_fetched: Number of sources fetched.
        total_chunks: Number of chunks created.
        total_embedded: Number of chunks embedded and stored.
    """

    total_fetched: int
    total_chunks: int
    total_embedded: int


class CorpusIngester(ABC):
    """Abstract base class for corpus ingestion pipelines.

    Subclasses implement fetch() to retrieve raw data and parse()
    to convert it into document chunks.
    """

    @abstractmethod
    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch jurisprudence sources from the data source.

        Returns:
            List of FonteJurisprudencia objects.
        """

    @abstractmethod
    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a raw source into document chunks.

        Args:
            raw: Raw data (typically a FonteJurisprudencia).

        Returns:
            List of document chunks ready for embedding.
        """
