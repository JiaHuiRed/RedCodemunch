"""Price a tier change against the cached schema it invalidates."""
from __future__ import annotations

import pytest

from jcodemunch_mcp import config as config_mod
from jcodemunch_mcp import server as server_mod
from jcodemunch_mcp.tier_switch_cost import (
    CACHE_READ_MULTIPLIER, CACHE_WRITE_MULTIPLIER, breakeven_requests, classify,
)

TIERS = ("core", "standard", "full")


# --------------------------------------------------------------------------- #
# The arithmetic
# --------------------------------------------------------------------------- #

def test_breakeven_is_write_cost_over_recurring_saving():
    # 10,000 -> 5,000: write 5,000 * 1.25 = 6,250; save 5,000 * 0.1 = 500.
    assert breakeven_requests(10_000, 5_000) == pytest.approx(12.5)


def test_history_only_ever_raises_the_breakeven():
    """⚠ `tools` is serialised AHEAD of system and messages, so the switch
    invalidates the accumulated turns too. Switching late is worse than early,
    and a price that ignores history is a FLOOR."""
    base = breakeven_requests(10_000, 5_000)
    prev = base
    for hist in (1_000, 10_000, 100_000):
        cur = breakeven_requests(10_000, 5_000, history_tokens=hist)
        assert cur > prev
        prev = cur


def test_a_widening_never_repays_and_is_not_a_defect():
    assert breakeven_requests(5_000, 10_000) is None
    assert classify(5_000, 10_000) == ("widening", None)


def test_noop_is_distinct_from_widening():
    assert classify(5_000, 5_000) == ("noop", None)


def test_classify_splits_paying_from_non_paying_at_the_horizon():
    verdict, be = classify(10_000, 5_000, horizon=100)
    assert (verdict, round(be, 1)) == ("pays", 12.5)
    # A 1% narrowing: tiny recurring saving, full-price write.
    verdict, be = classify(10_000, 9_900, horizon=100)
    assert verdict == "does_not_pay"
    assert be > 100


def test_the_multipliers_are_the_published_ones():
    """⚠ These are PUBLISHED rates, not measurements. Pinning them means a
    silent edit shows up as a failure rather than as a moved verdict."""
    assert (CACHE_READ_MULTIPLIER, CACHE_WRITE_MULTIPLIER) == (0.1, 1.25)


# --------------------------------------------------------------------------- #
# The measured surface
# --------------------------------------------------------------------------- #

def test_schema_tokens_per_profile_are_distinct_and_ordered():
    """The control. Every refusal test below is satisfied by a function that
    returns the same number for every tier."""
    weights = {t: server_mod._schema_tokens_for_profile(t) for t in TIERS}
    assert weights["core"] < weights["standard"] < weights["full"]
    assert weights["core"] > 0


def test_schema_tokens_price_what_the_client_ACTUALLY_receives():
    """⚠⚠ The first draft filtered the raw catalog by the tier bundle and was
    wrong by three tools in EVERY tier -- it kept the hidden front door and
    dropped the force-included tier controls. It priced a surface no client is
    ever sent. The only defensible source is the function `list_tools` uses."""
    for tier in TIERS:
        published = server_mod._build_tools_list(profile_override=tier)
        assert server_mod._schema_tokens_for_profile(tier) == sum(
            server_mod._schema_weight(t) for t in published
        )
        assert {"announce_model", "jcodemunch_guide"} <= {
            t.name for t in published
        }, f"{tier} dropped a force-included guide tool"


def test_profile_override_changes_nothing_when_omitted():
    assert [t.name for t in server_mod._build_tools_list()] == [
        t.name for t in server_mod._build_tools_list(profile_override=None)
    ]


def test_there_is_one_schema_weigher():
    """⚠ It was a closure inside `_tool_surface_stats` until pricing needed the
    same scale. Two copies that agree digit for digit are what make a later
    divergence invisible -- the `analyze_perf._percentile` lesson."""
    import inspect
    src = inspect.getsource(server_mod._tool_surface_stats)
    assert "_schema_weight" in src
    assert "def _weight" not in src


def test_standard_is_the_narrowing_that_does_not_pay():
    """The measurement this whole file exists for, asserted as a PROPERTY of
    the live catalog rather than as the literal 174."""
    verdict, be = classify(
        server_mod._schema_tokens_for_profile("full"),
        server_mod._schema_tokens_for_profile("standard"),
    )
    assert verdict == "does_not_pay"
    assert be > 100

    verdict, be = classify(
        server_mod._schema_tokens_for_profile("full"),
        server_mod._schema_tokens_for_profile("core"),
    )
    assert verdict == "pays", "core is the real narrowing and must stay allowed"
    assert be < 10


# --------------------------------------------------------------------------- #
# The shipped default map
# --------------------------------------------------------------------------- #

def test_no_default_map_entry_targets_a_switch_that_would_be_refused():
    """⚠⚠ Asserted as a PROPERTY, not as 'sonnet maps to full'. The old test
    pinned the map's contents, so it could only pass while the pessimizing
    route existed -- it was the defect's witness, not its guard.

    ⚠ Judged from `full`, the tier a session starts in by default and the only
    one any of these entries can narrow FROM.
    """
    full = server_mod._schema_tokens_for_profile("full")
    offenders = []
    for source, mapping in _shipped_maps().items():
        for pattern, tier in mapping.items():
            if tier not in TIERS:
                continue
            verdict, be = classify(full, server_mod._schema_tokens_for_profile(tier))
            if verdict == "does_not_pay":
                offenders.append(f"{source}: {pattern} -> {tier} ({be:,.0f} reqs)")
    assert not offenders, (
        "a shipped model_tier_map routes a model at a switch the server "
        "refuses: " + ", ".join(offenders)
    )


def _shipped_maps() -> "dict[str, dict]":
    """Every copy of the map that reaches a user.

    ⚠⚠ The first draft read `DEFAULTS` alone and passed while the CONFIG
    TEMPLATE -- the copy actually written into a user's `config.jsonc` -- still
    routed `claude-sonnet` and `gpt-4o` at `standard`. Fixing the constant and
    leaving the template is this project's most-repeated error: **we fix the
    reported call site and leave the mechanism.** A guard over one copy of a
    duplicated value is a guard over none.
    """
    import json
    import re
    from pathlib import Path

    maps = {"DEFAULTS": config_mod.DEFAULTS["model_tier_map"]}
    template = config_mod._fresh_config_content(Path("."))
    block = re.search(r'"model_tier_map":\s*(\{.*?\})', template, re.S)
    assert block, "the config template no longer declares model_tier_map"
    maps["config template"] = json.loads(block.group(1))
    return maps

# --------------------------------------------------------------------------- #
# The published counts carry their basis
# --------------------------------------------------------------------------- #

def test_every_schema_token_figure_ships_with_its_basis():
    """⚠⚠ A bare `schema_tokens_avoided` has no TIME basis, and a reader
    supplies the wrong one: per request. `benchmarks/codex_surface/` measured
    86% of baseline input cached and says in our own words that the
    "N tokens in every request" framing is wrong -- *and that this repository
    said exactly that before measuring*. The artifact knew; the shipped field
    did not.

    ⚠ Asserted as co-presence, not as a string: any consumer reading a count
    also receives the basis. The wording is allowed to improve.
    """
    from jcodemunch_mcp.tier_switch_cost import SCHEMA_TOKENS_BASIS

    stats = server_mod._tool_surface_stats(top_n=3)
    counts = [k for k in stats if k.startswith("schema_tokens_") and "basis" not in k]
    assert counts, "no schema token figures found -- this test asserts nothing"
    assert stats["schema_tokens_basis"] == SCHEMA_TOKENS_BASIS
    assert "cache" in stats["schema_tokens_basis_note"].lower()
    assert "not a per-request saving" in stats["schema_tokens_basis_note"].lower()


def test_the_count_is_not_silently_discounted():
    """⚠⚠ The fix is a LABEL, never a scaled number. A count quietly
    multiplied by the cache-read rate answers neither the payload question nor
    the cost question, and nothing on the wire would show it had happened.
    Same rule as `analyze_perf`'s raw `hit_rate`, kept beside its basis rather
    than replaced."""
    stats = server_mod._tool_surface_stats(top_n=3)
    visible = sum(server_mod._schema_weight(t) for t in server_mod._build_tools_list())
    catalog = sum(server_mod._schema_weight(t) for t in server_mod._raw_catalog_tools())
    assert stats["schema_tokens_visible"] == visible
    assert stats["schema_tokens_catalog"] == catalog
    assert stats["schema_tokens_avoided"] == max(0, catalog - visible)


def test_the_human_surface_prints_the_basis_too():
    """⚠ `jcodemunch-mcp surface` is where a person reads this number, and a
    person is exactly who supplies the wrong basis. A machine-readable field
    the CLI does not print leaves the human surface carrying the old defect."""
    import inspect
    src = inspect.getsource(server_mod)
    block = src.split("Schema tokens avoided:", 1)[1][:600]
    assert "schema_tokens_basis" in block, "the CLI prints the count without its basis"
