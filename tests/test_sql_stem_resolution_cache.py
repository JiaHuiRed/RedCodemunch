from jcodemunch_mcp.parser import imports
from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.tools.invalidate_cache import invalidate_cache


def test_frozen_lookup_is_cached_and_mutable_sets_refresh():
    imports._sql_stem_cache.clear()
    imports._sql_stem_by_files.clear()
    files = frozenset({"models/one.sql", "src/app.py"})
    first = imports._get_sql_stems(files)
    assert first == {"one": "models/one.sql"}
    assert imports._get_sql_stems(files) is first
    mutable = set(files)
    assert imports.resolve_specifier("one", "src/app.py", mutable) == "models/one.sql"
    mutable.add("models/two.sql")
    assert imports.resolve_specifier("two", "src/app.py", mutable) == "models/two.sql"


def test_relative_and_alias_resolution_remain_sensitive_to_inputs():
    files = frozenset({"src/a/dep.ts", "src/b/dep.ts", "src/a/app.ts", "src/b/app.ts"})
    assert imports.resolve_specifier("./dep", "src/a/app.ts", files) == "src/a/dep.ts"
    assert imports.resolve_specifier("./dep", "src/b/app.ts", files) == "src/b/dep.ts"
    aliases = {"@/*": ["src/a/*"]}
    assert imports.resolve_specifier("@/dep", "src/a/app.ts", files, aliases) == "src/a/dep.ts"
    aliases["@/*"] = ["src/b/*"]
    assert imports.resolve_specifier("@/dep", "src/a/app.ts", files, aliases) == "src/b/dep.ts"


def test_invalidate_clears_both_sql_caches(tmp_path):
    storage = str(tmp_path / "index")
    store = IndexStore(base_path=storage)
    store.save_index(owner="test", name="repo", source_files=["model.sql"],
                     symbols=[], raw_files={"model.sql": "select 1"}, languages={"sql": 1})
    files = frozenset({"model.sql"})
    assert imports.resolve_specifier("model", "main.sql", files) == "model.sql"
    assert imports._sql_stem_cache and imports._sql_stem_by_files
    assert invalidate_cache("test/repo", storage_path=storage)["success"]
    assert not imports._sql_stem_cache
    assert not imports._sql_stem_by_files
