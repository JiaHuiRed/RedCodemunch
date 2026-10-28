import json
import subprocess
import sys

import pytest

from jcodemunch_mcp.storage.index_store import IndexStore
from jcodemunch_mcp.storage import process_locks


def test_colliding_slots_reject_wrong_repository(tmp_path):
    store = IndexStore(base_path=str(tmp_path))
    store.save_index("foo-bar", "baz", ["a.txt"], [], {"a.txt": "first"})
    with pytest.raises(ValueError, match="foo-bar/baz"):
        store.load_index("foo", "bar-baz")


def test_colliding_save_must_preserve_existing_index(tmp_path):
    store = IndexStore(base_path=str(tmp_path))
    store.save_index("foo-bar", "baz", ["a.txt"], [], {"a.txt": "first"})
    with pytest.raises(ValueError, match="foo-bar/baz"):
        store.save_index("foo", "bar-baz", ["a.txt"], [], {"a.txt": "second"})
    assert store.get_file_content("foo-bar", "baz", "a.txt") == "first"


def test_colliding_identities_share_cross_process_lock(tmp_path):
    with process_locks.held("indexwrite", "foo-bar/baz", str(tmp_path)) as acquired:
        assert acquired
        code = (
            "from jcodemunch_mcp.storage.process_locks import held\n"
            "import sys\n"
            "with held('indexwrite', 'foo/bar-baz', sys.argv[1], wait_seconds=0) as got:\n"
            " print('acquired' if got else 'blocked')\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        assert child.stdout.strip() == "blocked"


def test_concurrent_colliding_saves_keep_winner_content(tmp_path):
    code = """
import sys, time
from pathlib import Path
from jcodemunch_mcp.storage.index_store import IndexStore
root, owner, name = sys.argv[1:]
gate = Path(root) / "start"
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() > deadline:
        raise TimeoutError("start gate")
    time.sleep(0.01)
try:
    IndexStore(base_path=root).save_index(owner, name, ["a.txt"], [], {"a.txt": owner})
    print("saved")
except ValueError as exc:
    print("refused", exc)
"""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path), owner, name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for owner, name in (("foo-bar", "baz"), ("foo", "bar-baz"))
    ]
    (tmp_path / "start").write_text("go", encoding="utf-8")
    results = [worker.communicate(timeout=30) for worker in workers]
    assert all(worker.returncode == 0 for worker in workers), results
    assert sorted(output.split()[0] for output, _ in results) == ["refused", "saved"]
    winner = results[0][0].startswith("saved")
    owner, name = ("foo-bar", "baz") if winner else ("foo", "bar-baz")
    assert IndexStore(base_path=str(tmp_path)).get_file_content(owner, name, "a.txt") == owner


def test_legacy_json_identity_checked_before_migration(tmp_path):
    store = IndexStore(base_path=str(tmp_path))
    json_path = tmp_path / "foo-bar-baz.json"
    json_path.write_text(json.dumps({
        "repo": "foo-bar/baz", "owner": "foo-bar", "name": "baz",
        "indexed_at": "2026-01-01", "source_files": [], "symbols": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="foo-bar/baz"):
        store.load_index("foo", "bar-baz")
    assert json_path.exists()
    index = store.load_index("foo-bar", "baz")
    assert index is not None and index.repo == "foo-bar/baz"
