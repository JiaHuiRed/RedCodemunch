"""Tests for v1.75.0 retrieval confidence (retrieval/confidence.py)."""

from __future__ import annotations

import pytest

from jcodemunch_mcp.retrieval.confidence import (
    attach_confidence,
    compute_confidence,
)


class TestComputeConfidence:
    def test_empty_results_yield_zero(self):
        out = compute_confidence([])
        assert out["confidence"] == 0.0

    def test_single_strong_result_is_high(self):
        out = compute_confidence([{"score": 12.0}])
        # gap is 1.0 (top1 dominates with no top2), strength saturates
        assert out["confidence"] >= 0.7

    def test_two_close_results_lowers_confidence(self):
        tight = compute_confidence([{"score": 5.0}, {"score": 4.9}])
        wide = compute_confidence([{"score": 5.0}, {"score": 0.5}])
        assert wide["confidence"] > tight["confidence"]

    def test_stale_index_lowers_confidence(self):
        fresh = compute_confidence([{"score": 8.0}], is_stale=False)
        stale = compute_confidence([{"score": 8.0}], is_stale=True)
        assert fresh["confidence"] > stale["confidence"]

    def test_identity_match_boosts_confidence(self):
        unknown = compute_confidence([{"score": 5.0}])
        known_identity = compute_confidence(
            [{"score": 5.0}], has_identity_match=True
        )
        assert known_identity["confidence"] > unknown["confidence"]

    def test_components_returned(self):
        out = compute_confidence([{"score": 5.0}, {"score": 1.0}])
        comps = out["components"]
        assert {"gap", "strength", "identity", "freshness"} <= set(comps)
        assert 0 <= comps["gap"] <= 1
        assert 0 <= comps["strength"] <= 1


class TestAttachConfidence:
    def test_default_reads_results_field(self):
        result = {"results": [{"score": 10.0}, {"score": 1.0}], "_meta": {}}
        out = attach_confidence(result)
        assert "confidence" in out["_meta"]
        assert 0.0 <= out["_meta"]["confidence"] <= 1.0

    def test_explicit_score_list_overrides_results(self):
        result = {"results": [], "_meta": {}}
        out = attach_confidence(
            result, scored_results=[{"score": 8.0}]
        )
        assert out["_meta"]["confidence"] > 0

    def test_components_included_when_requested(self):
        result = {"results": [{"score": 5.0}], "_meta": {}}
        attach_confidence(result, include_components=True)
        assert "confidence_components" in result["_meta"]


class TestSearchSymbolsAttachesConfidence:
    def test_search_symbols_carries_confidence_meta(self, tmp_path):
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.search_symbols import search_symbols

        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"
        store.mkdir()
        (src / "auth.py").write_text(
            "def authenticate_user():\n    pass\n\n"
            "def deauthenticate_user():\n    pass\n"
        )
        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True
        out = search_symbols(
            repo=r["repo"],
            query="authenticate_user",
            storage_path=str(store),
        )
        assert "_meta" in out
        assert "confidence" in out["_meta"]
        assert 0.0 <= out["_meta"]["confidence"] <= 1.0
