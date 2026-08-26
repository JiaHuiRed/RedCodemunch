"""Tests for T15: _meta.methodology + _meta.confidence_level on all 5 analytical tools.

All tests use the small_index / medium_index / hierarchy_index fixtures from conftest.py.
Tools that require git or a local repo (get_hotspots) are tested for
_meta field presence; git-specific results are not asserted.
"""

import pytest

from jcodemunch_mcp.tools.get_call_hierarchy import get_call_hierarchy
from jcodemunch_mcp.tools.get_impact_preview import get_impact_preview
from jcodemunch_mcp.tools.get_symbol_complexity import get_symbol_complexity
from jcodemunch_mcp.tools.get_hotspots import get_hotspots
from jcodemunch_mcp.tools.get_repo_health import get_repo_health
from jcodemunch_mcp.tools.search_symbols import search_symbols


def _first_function_id(repo, store):
    """Return the symbol ID of the first function in the index."""
    r = search_symbols(repo=repo, query="add", max_results=1,
                       detail_level="compact", storage_path=store)
    if r.get("results"):
        return r["results"][0]["id"]
    return None


_VALID_CONFIDENCE = {"low", "medium", "high"}


class TestGetCallHierarchyMeta:

    def test_methodology_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_call_hierarchy(repo=repo, symbol_id=sid, storage_path=store)
        assert "_meta" in r
        assert "methodology" in r["_meta"]
        # small_index has no function calls, so falls back to text_heuristic
        assert r["_meta"]["methodology"] == "text_heuristic"

    def test_confidence_level_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_call_hierarchy(repo=repo, symbol_id=sid, storage_path=store)
        assert "confidence_level" in r["_meta"]
        assert r["_meta"]["confidence_level"] in _VALID_CONFIDENCE

    def test_confidence_level_is_low(self, small_index):
        """Call hierarchy with no call data falls back to text heuristic — low confidence."""
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_call_hierarchy(repo=repo, symbol_id=sid, storage_path=store)
        assert r["_meta"]["confidence_level"] == "low"


class TestGetImpactPreviewMeta:

    def test_methodology_present(self, medium_index):
        repo, store = medium_index["repo"], medium_index["store"]
        r = search_symbols(repo=repo, query="get_user", max_results=1,
                           detail_level="compact", storage_path=store)
        if not r.get("results"):
            pytest.skip("no function in index")
        sid = r["results"][0]["id"]
        result = get_impact_preview(repo=repo, symbol_id=sid, storage_path=store)
        assert "_meta" in result
        assert "methodology" in result["_meta"]
        assert result["_meta"]["methodology"] == "ast_call_references"

    def test_confidence_level_present(self, medium_index):
        repo, store = medium_index["repo"], medium_index["store"]
        r = search_symbols(repo=repo, query="get_user", max_results=1,
                           detail_level="compact", storage_path=store)
        if not r.get("results"):
            pytest.skip("no function in index")
        sid = r["results"][0]["id"]
        result = get_impact_preview(repo=repo, symbol_id=sid, storage_path=store)
        assert result["_meta"]["confidence_level"] in _VALID_CONFIDENCE

    def test_confidence_level_is_medium(self, medium_index):
        """Impact preview uses AST call references — medium confidence."""
        repo, store = medium_index["repo"], medium_index["store"]
        r = search_symbols(repo=repo, query="get_user", max_results=1,
                           detail_level="compact", storage_path=store)
        if not r.get("results"):
            pytest.skip("no function in index")
        sid = r["results"][0]["id"]
        result = get_impact_preview(repo=repo, symbol_id=sid, storage_path=store)
        assert result["_meta"]["confidence_level"] == "medium"


class TestGetSymbolComplexityMeta:

    def test_methodology_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_symbol_complexity(repo=repo, symbol_id=sid, storage_path=store)
        assert "_meta" in r
        assert "methodology" in r["_meta"]
        assert r["_meta"]["methodology"] == "stored_metrics"

    def test_confidence_level_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_symbol_complexity(repo=repo, symbol_id=sid, storage_path=store)
        assert r["_meta"]["confidence_level"] in _VALID_CONFIDENCE

    def test_confidence_level_is_medium(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        sid = _first_function_id(repo, store)
        if sid is None:
            pytest.skip("no function in index")
        r = get_symbol_complexity(repo=repo, symbol_id=sid, storage_path=store)
        assert r["_meta"]["confidence_level"] == "medium"


class TestGetHotspotsMeta:

    def test_methodology_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_hotspots(repo=repo, storage_path=store)
        assert "_meta" in r
        assert "methodology" in r["_meta"]
        assert r["_meta"]["methodology"] == "complexity_x_churn"

    def test_confidence_level_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_hotspots(repo=repo, storage_path=store)
        assert r["_meta"]["confidence_level"] in _VALID_CONFIDENCE

    def test_confidence_level_is_medium(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_hotspots(repo=repo, storage_path=store)
        assert r["_meta"]["confidence_level"] == "medium"


class TestGetRepoHealthMeta:

    def test_methodology_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_repo_health(repo=repo, storage_path=store)
        assert "_meta" in r
        assert "methodology" in r["_meta"]
        assert r["_meta"]["methodology"] == "aggregate"

    def test_confidence_level_present(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_repo_health(repo=repo, storage_path=store)
        assert r["_meta"]["confidence_level"] in _VALID_CONFIDENCE

    def test_confidence_level_is_medium(self, small_index):
        repo, store = small_index["repo"], small_index["store"]
        r = get_repo_health(repo=repo, storage_path=store)
        assert r["_meta"]["confidence_level"] == "medium"
