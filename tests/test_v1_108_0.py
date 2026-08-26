"""v1.108.0 — explicit-paths indexing (Change A).

Change A adds `paths=[...]` to `index_folder` plus a `--paths-from FILE | -`
CLI flag on `jcodemunch-mcp index` so an agent can index exactly the files
git just touched without paying the cost of a full tree walk.
"""

from __future__ import annotations

import io
from pathlib import Path


# --------------------------------------------------------------------------- #
# Change A — explicit-paths indexing                                          #
# --------------------------------------------------------------------------- #

class TestExplicitPaths:
    def test_only_listed_files_indexed(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
        (tmp_path / "b.py").write_text("def beta():\n    return 2\n")
        (tmp_path / "c.py").write_text("def gamma():\n    return 3\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            paths=["a.py", "b.py"],
            use_ai_summaries=False,
            incremental=False,
        )
        assert result.get("success") is True, result
        # The fast-path response uses 'symbol_count'; full-path uses 'symbol_count'
        # via the index. Either way, gamma should NOT appear.
        # Hit the repo index and confirm.
        from jcodemunch_mcp.storage import IndexStore
        store = IndexStore()
        owner, repo_name = result["repo"].split("/", 1)
        idx = store.load_index(owner, repo_name)
        assert idx is not None
        sym_names = {(s.name if hasattr(s, "name") else s["name"]) for s in idx.symbols}
        assert "alpha" in sym_names
        assert "beta" in sym_names
        assert "gamma" not in sym_names

    def test_directory_in_paths_recurses(self, tmp_path: Path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "x.py").write_text("def x():\n    return 1\n")
        (sub / "y.py").write_text("def y():\n    return 2\n")
        (tmp_path / "outside.py").write_text("def outside():\n    return 3\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            paths=["pkg"],
            use_ai_summaries=False,
            incremental=False,
        )
        assert result.get("success") is True, result
        from jcodemunch_mcp.storage import IndexStore
        store = IndexStore()
        owner, repo_name = result["repo"].split("/", 1)
        idx = store.load_index(owner, repo_name)
        sym_names = {(s.name if hasattr(s, "name") else s["name"]) for s in idx.symbols}
        assert "x" in sym_names
        assert "y" in sym_names
        assert "outside" not in sym_names

    def test_outside_root_rejected(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def a():\n    return 1\n")
        elsewhere = tmp_path.parent  # ancestor — definitely outside

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            paths=[str(elsewhere / "evil.py")],
            use_ai_summaries=False,
            incremental=False,
        )
        # Either success with warnings, or graceful no-source-files error.
        warnings = result.get("warnings") or []
        assert any("outside" in str(w).lower() or "non-existent" in str(w).lower() for w in warnings) \
            or result.get("error", "").startswith("No source files")

    def test_unsupported_extension_skipped(self, tmp_path: Path):
        (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
        (tmp_path / "junk.bin").write_bytes(b"\x00\x01")

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            paths=["ok.py", "junk.bin"],
            use_ai_summaries=False,
            incremental=False,
        )
        assert result.get("success") is True
        warnings = result.get("warnings") or []
        assert any("junk.bin" in str(w) and "unsupported" in str(w).lower() for w in warnings)

    def test_secret_file_in_paths_rejected(self, tmp_path: Path):
        """An explicitly-listed credential file must be refused, matching the
        full walk. Regression for the paths=[...] secret-filter bypass — the
        explicit branch checked only symlink/extension/size, so a caller naming
        a .env / secrets/*.yaml / credentials.json indexed it and it was then
        served unredacted by the source-dump tools.
        """
        from jcodemunch_mcp.tools.index_folder import (
            resolve_explicit_paths,
            discover_local_files,
        )
        from jcodemunch_mcp.security import is_secret_file

        (tmp_path / "config" / "secrets").mkdir(parents=True)
        (tmp_path / "config" / "secrets" / "database.yaml").write_text(
            "aws_secret_access_key: AKIAIOSFODNN7EXAMPLE\npassword: hunter2\n"
        )
        (tmp_path / "credentials.json").write_text(
            '{"aws_secret_access_key": "AKIAIOSFODNN7EXAMPLE"}\n'
        )
        (tmp_path / "app.py").write_text("def app():\n    return 1\n")

        # Sanity: the classifier flags both.
        assert is_secret_file("config/secrets/database.yaml")
        assert is_secret_file("credentials.json")

        files, warnings, skip_counts, _req = resolve_explicit_paths(
            tmp_path,
            ["config/secrets/database.yaml", "credentials.json", "app.py"],
            max_files=100,
        )
        names = sorted(f.name for f in files)
        assert names == ["app.py"], names
        assert skip_counts.get("secret") == 2, skip_counts
        assert any("secret" in w.lower() for w in warnings), warnings

        # Parity with the full walk: it refuses the same two files.
        walk_files, _ww, walk_skip = discover_local_files(tmp_path, max_files=100)
        assert sorted(f.name for f in walk_files) == ["app.py"]
        assert walk_skip.get("secret") == 2, walk_skip

    def test_secret_symbols_never_reach_index_via_paths(self, tmp_path: Path):
        """End-to-end: index_folder(paths=[secret]) must not persist the
        credential file's contents into the index."""
        (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
        (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            paths=["ok.py", ".env"],
            use_ai_summaries=False,
            incremental=False,
        )
        assert result.get("success") is True, result
        from jcodemunch_mcp.storage import IndexStore
        store = IndexStore()
        owner, repo_name = result["repo"].split("/", 1)
        idx = store.load_index(owner, repo_name)
        indexed_files = {
            (s.file if hasattr(s, "file") else s.get("file")) for s in idx.symbols
        }
        assert not any(str(f).endswith(".env") for f in indexed_files if f), indexed_files

    def test_paths_omitted_does_full_walk(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
        (tmp_path / "b.py").write_text("def beta():\n    return 2\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        result = index_folder(
            path=str(tmp_path),
            use_ai_summaries=False,
            incremental=False,
        )
        assert result.get("success") is True
        from jcodemunch_mcp.storage import IndexStore
        store = IndexStore()
        owner, repo_name = result["repo"].split("/", 1)
        idx = store.load_index(owner, repo_name)
        sym_names = {(s.name if hasattr(s, "name") else s["name"]) for s in idx.symbols}
        # Both got indexed via the full walk
        assert "alpha" in sym_names
        assert "beta" in sym_names


class TestLoadIndexPathsFromArg:
    """Unit-test the CLI's --paths-from file/stdin reader helper."""

    def test_reads_file_strips_blanks_and_comments(self, tmp_path: Path):
        from jcodemunch_mcp.server import _load_index_paths_from_arg
        f = tmp_path / "p.txt"
        f.write_text("a.py\n\n# comment\n  b.py  \nsubdir/c.py\n", encoding="utf-8")
        paths, err = _load_index_paths_from_arg(str(f))
        assert err is None
        assert paths == ["a.py", "b.py", "subdir/c.py"]

    def test_reads_stdin(self, monkeypatch):
        from jcodemunch_mcp.server import _load_index_paths_from_arg
        monkeypatch.setattr("sys.stdin", io.StringIO("x.py\ny.py\n"))
        paths, err = _load_index_paths_from_arg("-")
        assert err is None
        assert paths == ["x.py", "y.py"]

    def test_empty_returns_error(self, tmp_path: Path):
        from jcodemunch_mcp.server import _load_index_paths_from_arg
        f = tmp_path / "empty.txt"
        f.write_text("\n# nothing useful\n", encoding="utf-8")
        paths, err = _load_index_paths_from_arg(str(f))
        assert paths is None
        assert err is not None
        assert "no usable paths" in err.lower()

    def test_missing_file_returns_error(self, tmp_path: Path):
        from jcodemunch_mcp.server import _load_index_paths_from_arg
        paths, err = _load_index_paths_from_arg(str(tmp_path / "missing.txt"))
        assert paths is None
        assert "cannot read" in (err or "").lower()
