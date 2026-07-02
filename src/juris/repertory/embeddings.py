"""Legal text embeddings via sentence-transformers.

Wraps BGE-M3 (or configurable model) for dense vector generation.
Supports lazy loading and graceful fallback when model is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-m3"
_DEFAULT_DIMENSION = 1024  # BGE-M3 output dimension


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
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._model: Any | None = None
        self._dimension: int = _DEFAULT_DIMENSION

    def _load_model(self) -> None:
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)
            dim = self._model.get_sentence_embedding_dimension()
            if dim is not None:
                self._dimension = int(dim)
            logger.info("Loaded embedding model %s on %s (dim=%d)", self._model_name, self._device, self._dimension)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not load embedding model '%s'. "
                "Install sentence-transformers and download the model. "
                "Embeddings will return None.",
                self._model_name,
            )
            self._model = None

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, or None if model unavailable.
        """
        self._load_model()
        if self._model is None:
            return None
        try:
            embeddings = self._model.encode(texts, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as exc:  # noqa: BLE001
            from juris.core.sanitize import safe_error_text

            logger.warning("Failed to embed %d texts: %s", len(texts), safe_error_text(exc))
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
