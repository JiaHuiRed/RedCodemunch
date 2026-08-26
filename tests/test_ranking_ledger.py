"""Tests for v1.78.0 ranking ledger."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jcodemunch_mcp.storage import token_tracker as tt
from jcodemunch_mcp.retrieval.confidence import extract_ledger_features


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    fresh = tt._State()
    fresh._base_path = str(tmp_path)
    monkeypatch.setattr(tt, "_state", fresh)
    yield


def _enable(monkeypatch):
    from jcodemunch_mcp import config as _config
    real_get = _config.get

    def patched_get(key, default=None, *args, **kwargs):
        if key == "perf_telemetry_enabled":
            return True
        return real_get(key, default, *args, **kwargs)

    monkeypatch.setattr(_config, "get", patched_get)


class TestExtractLedgerFeatures:
    def test_empty(self):
        out = extract_ledger_features([])
        assert out["top1_score"] is None
        assert out["top2_score"] is None
        assert out["identity_hit"] is False

    def test_single_with_score(self):
        out = extract_ledger_features([{"score": 9.0}])
        assert out["top1_score"] == 9.0
        assert out["top2_score"] is None

    def test_pair_with_identity(self):
        out = extract_ledger_features(
            [{"score": 12.0, "identity_match": True}, {"score": 4.0}]
        )
        assert out["top1_score"] == 12.0
        assert out["top2_score"] == 4.0
        assert out["identity_hit"] is True

    def test_non_numeric_score_returns_none(self):
        out = extract_ledger_features([{"score": "oops"}])
        assert out["top1_score"] is None


class TestLedgerPersistence:
    def test_disabled_no_db(self, tmp_path):
        tt.record_ranking_event(
            tool="search_symbols",
            repo="local/x",
            query="foo",
            returned_ids=["a", "b"],
            top1_score=5.0,
            top2_score=1.0,
            confidence=0.8,
            semantic_used=False,
            identity_hit=False,
        )
        # Telemetry not enabled → no db file
        assert not (tmp_path / "telemetry.db").exists()

    def test_enabled_appends_row(self, monkeypatch, tmp_path):
        _enable(monkeypatch)
        tt.record_ranking_event(
            tool="search_symbols",
            repo="local/x",
            query="auth",
            returned_ids=["a", "b", "c"],
            top1_score=5.0,
            top2_score=1.0,
            confidence=0.8,
            semantic_used=False,
            identity_hit=True,
            repo_is_stale=False,
        )
        db = tmp_path / "telemetry.db"
        assert db.exists()
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT tool, repo, query, returned_ids, top1_score, top2_score, "
            "confidence, semantic_used, identity_hit, repo_is_stale "
            "FROM ranking_events"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        row = rows[0]
        assert row[0] == "search_symbols"
        assert row[1] == "local/x"
        assert row[2] == "auth"
        assert json.loads(row[3]) == ["a", "b", "c"]
        assert row[4] == 5.0
        assert row[5] == 1.0
        assert row[6] == 0.8
        assert row[7] == 0
        assert row[8] == 1
        assert row[9] == 0

    def test_query_hash_is_stable(self, monkeypatch, tmp_path):
        _enable(monkeypatch)
        tt.record_ranking_event(
            tool="search_symbols",
            repo=None,
            query="same query",
            returned_ids=[],
            semantic_used=False,
            identity_hit=False,
        )
        tt.record_ranking_event(
            tool="search_symbols",
            repo=None,
            query="same query",
            returned_ids=[],
            semantic_used=False,
            identity_hit=False,
        )
        conn = sqlite3.connect(str(tmp_path / "telemetry.db"))
        hashes = [r[0] for r in conn.execute("SELECT query_hash FROM ranking_events")]
        conn.close()
        assert len(hashes) == 2
        assert hashes[0] == hashes[1]


class TestRankingDbQuery:
    def test_no_db_returns_empty(self, tmp_path):
        rows = tt.ranking_db_query(base_path=str(tmp_path))
        assert rows == []

    def test_filters_by_repo_and_tool(self, monkeypatch, tmp_path):
        _enable(monkeypatch)
        for q, repo, tool in [
            ("a", "r1", "search_symbols"),
            ("b", "r2", "search_symbols"),
            ("c", "r1", "plan_turn"),
        ]:
            tt.record_ranking_event(
                tool=tool, repo=repo, query=q, returned_ids=[],
                semantic_used=False, identity_hit=False,
            )
        out = tt.ranking_db_query(base_path=str(tmp_path), repo="r1")
        assert len(out) == 2
        out2 = tt.ranking_db_query(base_path=str(tmp_path), tool="plan_turn")
        assert len(out2) == 1
        assert out2[0][2] == "plan_turn"  # tool column index


class TestSearchSymbolsRecordsLedgerEvent:
    def test_search_invokes_record_ranking_event(self, tmp_path, monkeypatch):
        """Patch the recorder to capture invocations from search_symbols."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.search_symbols import search_symbols
        from jcodemunch_mcp.storage import token_tracker as _tt

        captured: list[dict] = []

        def fake_record(**kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(_tt, "record_ranking_event", fake_record)

        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"
        store.mkdir()
        (src / "auth.py").write_text("def authenticate():\n    pass\n")
        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        out = search_symbols(repo=r["repo"], query="authenticate", storage_path=str(store))
        assert out["result_count"] >= 1
        assert len(captured) == 1
        ev = captured[0]
        assert ev["tool"] == "search_symbols"
        assert ev["query"] == "authenticate"
        assert isinstance(ev["returned_ids"], list)
        assert "confidence" in ev
