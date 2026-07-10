"""Legal text embeddings via sentence-transformers.

Wraps BGE-M3 (or configurable model) for dense vector generation.
Production fails closed when embeddings cannot be loaded; development can still
fall back to keyword-only retrieval.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-m3"
_DEFAULT_DIMENSION = 1024  # BGE-M3 output dimension
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


class EmbeddingModelUnavailableError(RuntimeError):
    """Raised when semantic retrieval is required but the embedding model is unavailable."""


def embeddings_required_by_environment() -> bool:
    """Return whether missing embeddings should be treated as a hard failure."""
    explicit = os.getenv("JURIS_REQUIRE_EMBEDDINGS", "").strip().lower()
    if explicit in _TRUE_VALUES:
        return True
    if explicit in _FALSE_VALUES:
        return False
    return os.getenv("ENVIRONMENT", "").strip().lower() == "prod"


class LegalEmbedder:
    """Wraps sentence-transformers BGE-M3 for legal text embeddings.

    Args:
        model_name: HuggingFace model identifier.
        device: Computation device ('cpu', 'mps', 'cuda').
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        device: str = "cpu",
        required: bool | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._required = embeddings_required_by_environment() if required is None else required
        self._model: Any | None = None
        self._dimension: int = _DEFAULT_DIMENSION
        self._load_attempted = False
        self._load_error: str | None = None

    def _load_model(self) -> None:
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return
        if self._load_attempted:
            if self._required and self._load_error:
                raise EmbeddingModelUnavailableError(self._load_error)
            return
        self._load_attempted = True
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)
            dim = self._model.get_sentence_embedding_dimension()
            if dim is not None:
                self._dimension = int(dim)
            logger.info("Loaded embedding model %s on %s (dim=%d)", self._model_name, self._device, self._dimension)
        except Exception as exc:  # noqa: BLE001
            msg = (
                f"Embedding model '{self._model_name}' unavailable. "
                "Install sentence-transformers and pre-download the model cache."
            )
            logger.warning(
                "Could not load embedding model '%s'. "
                "Install sentence-transformers and download the model. "
                "required=%s",
                self._model_name,
                self._required,
            )
            self._model = None
            self._load_error = msg
            if self._required:
                raise EmbeddingModelUnavailableError(msg) from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, or None if model unavailable.
        """
        self._load_model()
        if self._model is None:
            if self._required:
                msg = self._load_error or f"Embedding model '{self._model_name}' unavailable."
                raise EmbeddingModelUnavailableError(msg)
            return None
        try:
            embeddings = self._model.encode(texts, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as exc:  # noqa: BLE001
            from juris.core.sanitize import safe_error_text

            msg = f"Failed to embed {len(texts)} text(s): {safe_error_text(exc)}"
            logger.warning("%s", msg)
            if self._required:
                raise EmbeddingModelUnavailableError(msg) from exc
            return None

    def embed_single(self, text: str) -> list[float] | None:
        """Embed a single text.

        Args:
            text: Text string to embed.

        Returns:
            Embedding vector, or None if model unavailable.
        """
        result = self.embed_texts([text])
        if result is None:
            return None
        return result[0]

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @property
    def required(self) -> bool:
        """Whether unavailable embeddings are a hard failure."""
        return self._required
