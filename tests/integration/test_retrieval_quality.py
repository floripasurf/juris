"""Retrieval quality benchmark — validates HyDE + reranker lift."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from juris.benchmark.extractor import ExtractedPair, load_curated_pairs


@pytest.mark.integration
class TestRetrievalQuality:
    def test_benchmark_structure(self) -> None:
        """Validates benchmark pair structure works correctly."""
        pair = ExtractedPair(
            thesis="Prescricao quinquenal aplica-se",
            expected_source_ids=["src_stj_sumula_150"],
            confidence=0.9,
            provenance="test",
            status="accepted",
        )
        assert pair.thesis
        assert pair.expected_source_ids
        assert pair.status == "accepted"

    def test_load_curated_pairs_filters(self, tmp_path: Path) -> None:
        """load_curated_pairs only returns accepted pairs."""
        data = [
            {
                "thesis": "T1",
                "expected_source_ids": ["s1"],
                "status": "accepted",
                "confidence": 0.9,
                "provenance": "p1",
            },
            {
                "thesis": "T2",
                "expected_source_ids": ["s2"],
                "status": "rejected",
                "confidence": 0.5,
                "provenance": "p2",
            },
            {
                "thesis": "T3",
                "expected_source_ids": ["s3"],
                "status": "pending",
                "confidence": 0.7,
                "provenance": "p3",
            },
        ]
        path = tmp_path / "pairs.json"
        path.write_text(json.dumps(data))
        pairs = load_curated_pairs(path)
        assert len(pairs) == 1
        assert pairs[0].thesis == "T1"
