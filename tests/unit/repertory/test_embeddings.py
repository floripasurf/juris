"""Embedding runtime safety: semantic retrieval must be observable in prod."""

from __future__ import annotations

import builtins

import pytest

from juris.repertory.embeddings import EmbeddingModelUnavailableError, LegalEmbedder


def _block_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001, ANN202 - test import hook
        if name == "sentence_transformers":
            raise RuntimeError("offline model cache")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_optional_embedder_degrades_to_none_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sentence_transformers(monkeypatch)

    embedder = LegalEmbedder(required=False)

    assert embedder.embed_single("honorarios sucumbenciais") is None
    assert embedder.required is False


def test_required_embedder_fails_closed_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sentence_transformers(monkeypatch)

    embedder = LegalEmbedder(required=True)

    with pytest.raises(EmbeddingModelUnavailableError):
        embedder.embed_single("honorarios sucumbenciais")


def test_prod_environment_requires_embeddings_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sentence_transformers(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.delenv("JURIS_REQUIRE_EMBEDDINGS", raising=False)

    embedder = LegalEmbedder()

    assert embedder.required is True
    with pytest.raises(EmbeddingModelUnavailableError):
        embedder.embed_single("honorarios sucumbenciais")
