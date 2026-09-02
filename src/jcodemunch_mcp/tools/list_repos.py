"""List indexed repositories."""

import time
from typing import Optional

from ..storage import IndexStore



# `get_watch_status` speaks the FreshnessProbe vocabulary; this listing has its
# own older labels. Map explicitly rather than passing the raw value through --
# `not_tracked` (a plain folder with no revision to compare) and `unknown` (a
# comparison we should have been able to make and could not) are different
# facts, and collapsing either into "fresh" is #565.
_FRESHNESS_LABEL = {
    "fresh": "fresh",
    "stale": "stale_index",
    "unknown": "unknown",
    "not_tracked": "not_tracked",
}

def list_repos(storage_path: Optional[str] = None) -> dict:
    """List all indexed repositories.

    Returns:
        Dict with count, list of repos, freshness summary, and _meta envelope.

    Freshness is measured by the existing ``repos_report`` path rather than
    inferred from watcher bookkeeping. A cold process must not present an
    unmeasured index as fresh.
    """
    start = time.perf_counter()
    store = IndexStore(base_path=storage_path)
    repos = store.list_repos()
    elapsed = (time.perf_counter() - start) * 1000

    result = {
        "count": len(repos),
        "repos": repos,
        "_meta": {
            "timing_ms": round(elapsed, 1),
        },
    }

    # `list_repos` is the normal entry point exposed to agents. Include the
    # same freshness vocabulary as the cockpit report so callers do not need a
    # second, non-obvious tool just to decide whether search results are safe
    # to trust.
    try:
        report = repos_report(storage_path)
    except Exception:
        # Listing remains useful when the optional watcher/service probe cannot
        # run, but the response must say that freshness was not established.
        result["_meta"]["freshness_checked"] = False
        result["freshness"] = {
            "checked": False,
            "any_stale": None,
            "any_unknown": True,
            "any_not_tracked": None,
        }
    else:
        by_repo = {entry.get("repo_id"): entry for entry in report}
        for repo in result["repos"]:
            status = by_repo.get(repo.get("repo"))
            if status is None:
                repo["freshness"] = "unknown"
                repo["watcher_state"] = "unknown"
                repo["lock_holder"] = None
                continue
            repo["freshness"] = status["freshness"]
            repo["watcher_state"] = status["watcher_state"]
            repo["lock_holder"] = status["lock_holder"]
        result["_meta"]["freshness_checked"] = True
        result["freshness"] = {
            "checked": True,
            "any_stale": any(
                entry["freshness"] == "stale_index" for entry in report
            ),
            "any_unknown": any(
                entry["freshness"] == "unknown" for entry in report
            ),
            "any_not_tracked": any(
                entry["freshness"] == "not_tracked" for entry in report
            ),
        }

    # Empty-store nudge (jcm#375 correspondence, suggestion C). A user ran the
    # suite for months with jdatamunch holding zero datasets and jdocmunch
    # holding three documents, and only found out by going looking: every tool
    # answered confidently regardless of how little it held. An empty listing is
    # indistinguishable from a broken one unless it says so.
    #
    # Top-level rather than under `_meta` deliberately: the sibling servers strip
    # `_meta` by default, so a nudge placed there would be deleted before the
    # agent ever saw it. Same key names across all three servers.
    if not repos:
        result["empty"] = True
        result["hint"] = (
            "No repositories are indexed yet, so every search will come back "
            "empty regardless of the query. Index one with "
            "index_folder(path='.') or the `jcodemunch-mcp index` CLI."
        )
    return result


def repos_report(storage_path: Optional[str] = None) -> list[dict]:
    """Cockpit view of indexed repos: per-repo counts + freshness + watcher state.

    Joins `list_repos` metadata (counts, languages, indexed_at) with
    `get_watch_status` (staleness + watcher lock holder), keyed by source_root.
    Structured for the jMunch Console index/watcher cockpit, but general-purpose.
    Watch status only covers discovered repos, so a repo it doesn't cover
    defaults to fresh/idle (no staleness signal available).
    """
    store = IndexStore(base_path=storage_path)
    repos = store.list_repos()
    try:
        from .get_watch_status import get_watch_status
        ws = get_watch_status(storage_path)
        ws_by_root = {r.get("source_root"): r for r in ws.get("repos", [])}
    except Exception:
        ws_by_root = {}

    report: list[dict] = []
    for r in repos:
        w = ws_by_root.get(r.get("source_root", ""), {})
        if w.get("reindex_in_progress"):
            watcher_state = "reindexing"
        elif w.get("watcher_holder"):
            watcher_state = "watching"
        else:
            watcher_state = "idle"
        holder = w.get("watcher_holder") or {}
        report.append({
            "repo_id": r.get("repo", ""),
            "display_name": r.get("display_name") or r.get("repo", ""),
            "source_root": r.get("source_root", ""),
            "file_count": r.get("file_count", 0),
            "symbol_count": r.get("symbol_count", 0),
            "languages": r.get("languages", {}) or {},
            "indexed_at": r.get("indexed_at", ""),
            # ⚠⚠ Was `"stale_index" if w.get("index_stale") else "fresh"`, which
            # inherited #565 wholesale: `index_stale` was watcher bookkeeping,
            # so this published `fresh` for every repo on any box whose watcher
            # had never run -- including repos that are not git-backed at all
            # and can never be compared. Reports what was measured now.
            "freshness": _FRESHNESS_LABEL.get(
                w.get("index_freshness"), "unknown"
            ),
            "watcher_state": watcher_state,
            "lock_holder": holder.get("client_id"),
        })
    return report
