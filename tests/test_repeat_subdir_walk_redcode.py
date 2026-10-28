import subprocess
import importlib

from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.tools.index_folder import index_folder


def test_repeat_subdir_incremental_scopes_deletions(tmp_path, monkeypatch):
    module = importlib.import_module("jcodemunch_mcp.tools.index_folder")
    parse = module.parse_file
    parsed = []

    def count_parse(content, path, *args, **kwargs):
        parsed.append(path)
        return parse(content, path, *args, **kwargs)

    monkeypatch.setattr(module, "parse_file", count_parse)
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "pkg").mkdir()
    (root / "other").mkdir()
    (root / "pkg" / "one.py").write_text("def one(): pass\n")
    (root / "pkg" / "two.py").write_text("def two(): pass\n")
    (root / "other" / "keep.py").write_text("def keep(): pass\n")
    storage = tmp_path / "index"

    def run(path, incremental=True):
        result = index_folder(
            str(path), storage_path=str(storage), use_ai_summaries=False,
            context_providers=False, identity_mode="git", incremental=incremental,
        )
        assert result["success"], result
        return result

    run(root / "other")
    first = run(root / "pkg")
    assert first["performed_incremental"] is False
    parsed.clear()
    run(root / "pkg", incremental=False)
    assert len(parsed) == 2
    parsed.clear()
    repeat = run(root / "pkg")
    assert repeat["performed_incremental"] is True, repeat
    assert repeat["message"] == "No changes detected"
    assert parsed == []

    (root / "pkg" / "one.py").unlink()
    (root / "pkg" / "two.py").write_text("def updated(): return 42\n")
    (root / "pkg" / "new.py").write_text("def new(): pass\n")
    changed = run(root / "pkg")
    assert changed["performed_incremental"] is True, changed
    assert changed["deleted"] == 1
    assert changed["new"] == 1
    owner, name = first["repo"].split("/", 1)
    index = IndexStore(str(storage)).load_index(owner, name)
    assert set(index.source_files) == {"pkg/two.py", "pkg/new.py", "other/keep.py"}
    assert {s["name"] for s in index.symbols} >= {"updated", "new", "keep"}
