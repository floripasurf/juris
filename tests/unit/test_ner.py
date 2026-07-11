"""Tests for the legal NER redactor (LeNER-Br) — closes the de-id name gap."""

from __future__ import annotations

from juris.core.ner import LegalNER


def _pipe(entities):
    return lambda _text: entities


def test_redacts_person_and_org_names() -> None:
    ner = LegalNER(
        pipeline=_pipe(
            [
                {"entity_group": "PESSOA", "word": "João da Silva"},
                {"entity_group": "ORGANIZACAO", "word": "Acme Ltda"},
                {"entity_group": "TEMPO", "word": "2020"},
                {"entity_group": "LEGISLACAO", "word": "art. 5º"},
            ]
        )
    )
    spans = ner.redact_entities("...")
    assert "João da Silva" in spans
    assert "Acme Ltda" in spans
    assert "2020" not in spans  # non-PII entity types are not redacted
    assert "art. 5º" not in spans


def test_dedups_and_orders_longest_first() -> None:
    ner = LegalNER(
        pipeline=_pipe(
            [
                {"entity_group": "PESSOA", "word": "João"},
                {"entity_group": "PESSOA", "word": "João da Silva"},
                {"entity_group": "PESSOA", "word": "João da Silva"},
            ]
        )
    )
    spans = ner.redact_entities("...")
    assert spans == ["João da Silva", "João"]  # longest first so the full name redacts first


def test_handles_entity_key_alias() -> None:
    # Some pipelines emit "entity" instead of "entity_group".
    ner = LegalNER(pipeline=_pipe([{"entity": "PESSOA", "word": "Maria"}]))
    assert ner.redact_entities("...") == ["Maria"]
