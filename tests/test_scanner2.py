"""
Tests for devdna.core.scanner2

Run: pytest tests/test_scanner2.py -v
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def config_override(**kwargs):
    """Temporarily set fields on the frozen Config singleton."""
    from devdna.config import config as cfg
    saved = dict(cfg.__dict__)
    for k, v in kwargs.items():
        object.__setattr__(cfg, k, v)
    try:
        yield cfg
    finally:
        object.__setattr__(cfg, "__dict__", saved)

from devdna.core.scanner import CodeBlock as CodeBlockV1
from devdna.core import scanner2
from devdna.core.scanner2 import (
    CodeBlock,
    extract_functions,
    scan_directory,
    iter_scan_directory,
    discover_python_files,
)


# =============================================================================
# Regression Tests (bugs found in original scanner2)
# =============================================================================

class TestNormalizerRegressions:
    """Regressions for bugs in the original NodeTransformer implementation."""

    def test_function_with_keyword_args_not_dropped(self, tmp_path: Path):
        """CRITICAL REGRESSION: visit_keyword used to return a fresh keyword
        without .value, making unparse fail and silently dropping every
        function containing a keyword argument."""
        f = tmp_path / "kw.py"
        f.write_text("def foo(a, b=1):\n    return dict(x=a, y=2)")
        blocks = extract_functions(f)
        assert len(blocks) == 1
        assert blocks[0].func_name == "foo"

    def test_keyword_arg_normalized(self, tmp_path: Path):
        """Keyword argument names become VAR but call values survive."""
        f = tmp_path / "kwnorm.py"
        f.write_text("def foo(dataframe):\n    return dataframe.merge(left=dataframe)")
        blocks = extract_functions(f)
        assert len(blocks) == 1
        assert "VAR" in blocks[0].normalized
        assert "left=" not in blocks[0].normalized.replace("VAR=", "left=")

    def test_annotations_preserved_for_v1_hash_parity(self, tmp_path: Path):
        """visit_arg used to drop annotations entirely; v1 kept them.
        Hashes must match scanner v1 for identical source."""
        src = "def foo(a: int, b: str = 'x') -> bool:\n    return len(a) > 1"
        f = tmp_path / "ann.py"
        f.write_text(src)
        b2 = extract_functions(f)[0]
        b1 = CodeBlockV1(
            source_code=src,
            filepath=f,
            func_name="foo",
            lineno=1,
        )
        assert b1.struct_hash == b2.struct_hash

    def test_hash_parity_plain_function(self, tmp_path: Path):
        """scanner and scanner2 produce identical hashes for plain code."""
        src = "def calc(items):\n    total = 0\n    for i in items:\n        total += i\n    return total"
        f = tmp_path / "plain.py"
        f.write_text(src)
        b2 = extract_functions(f)[0]
        b1 = CodeBlockV1(source_code=src, filepath=f, func_name="calc", lineno=1)
        assert b1.struct_hash == b2.struct_hash


# =============================================================================
# Extraction Behavior Tests
# =============================================================================

class TestExtractFunctions:
    def test_extracts_simple_function(self, tmp_path: Path):
        f = tmp_path / "simple.py"
        f.write_text("def hello():\n    return 1")
        blocks = extract_functions(f)
        assert len(blocks) == 1
        assert blocks[0].func_name == "hello"

    def test_extracts_async_function(self, tmp_path: Path):
        f = tmp_path / "async.py"
        f.write_text("async def fetch(url):\n    return url")
        blocks = extract_functions(f)
        assert len(blocks) == 1
        assert blocks[0].func_name == "fetch"
        assert "AsyncFunc" not in blocks[0].normalized or "FUNC" in blocks[0].normalized

    def test_skips_pass_stub(self, tmp_path: Path):
        f = tmp_path / "stub.py"
        f.write_text("def stub():\n    pass")
        assert extract_functions(f) == []

    def test_skips_docstring_only(self, tmp_path: Path):
        f = tmp_path / "doc.py"
        f.write_text('def doc():\n    """Docs only."""')
        assert extract_functions(f) == []

    def test_skips_ellipsis_stub(self, tmp_path: Path):
        f = tmp_path / "ell.py"
        f.write_text("def ell():\n    ...")
        assert extract_functions(f) == []

    def test_docstring_stripped_from_normalization(self, tmp_path: Path):
        """Docstrings are stripped before hashing."""
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text('def foo(x):\n    """A doc."""\n    return x + 1')
        f2.write_text("def foo(y):\n    return y + 1")
        b1 = extract_functions(f1)[0]
        b2 = extract_functions(f2)[0]
        assert b1.struct_hash == b2.struct_hash

    def test_nested_functions_both_extracted(self, tmp_path: Path):
        f = tmp_path / "nested.py"
        f.write_text("def outer():\n    def inner():\n        return 1\n    return inner")
        blocks = extract_functions(f)
        names = {b.func_name for b in blocks}
        assert names == {"outer", "inner"}

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert extract_functions(f) == []

    def test_syntax_error(self, tmp_path: Path):
        f = tmp_path / "broken.py"
        f.write_text("def broken(:")
        assert extract_functions(f) == []

    def test_oversized_ast_guard(self, tmp_path: Path):
        """Files exceeding max_ast_nodes are skipped entirely."""
        f = tmp_path / "big.py"
        f.write_text("def a():\n    x = 1\n    y = 2\n    z = 3\n    return x + y + z")
        with config_override(max_ast_nodes=5):
            assert extract_functions(f) == []
        # default limit still extracts normally
        assert len(extract_functions(f)) == 1

    def test_lineno_preserved(self, tmp_path: Path):
        f = tmp_path / "lines.py"
        f.write_text("# comment\n\ndef foo():\n    return 1")
        blocks = extract_functions(f)
        assert blocks[0].lineno == 3


# =============================================================================
# Discovery Tests
# =============================================================================

class TestDiscovery:
    def test_finds_python_files_recursively(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def f(): return 1")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("def g(): return 2")
        files = discover_python_files(tmp_path, {"venv"})
        assert len(files) == 2

    def test_prunes_excluded_dirs(self, tmp_path: Path):
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "deep.py").write_text("def deep(): return 1")
        (tmp_path / "real.py").write_text("def real(): return 1")
        files = discover_python_files(tmp_path, {"venv"})
        assert [f.name for f in files] == ["real.py"]

    def test_prunes_hidden_dirs(self, tmp_path: Path):
        hidden = tmp_path / ".git" / "hooks"
        hidden.mkdir(parents=True)
        (hidden / "hook.py").write_text("def hook(): return 1")
        assert discover_python_files(tmp_path, set()) == []

    def test_skips_hidden_files(self, tmp_path: Path):
        (tmp_path / ".secret.py").write_text("def s(): return 1")
        assert discover_python_files(tmp_path, set()) == []

    def test_only_matching_extensions(self, tmp_path: Path):
        (tmp_path / "code.py").write_text("def a(): return 1")
        (tmp_path / "notes.txt").write_text("not code")
        files = discover_python_files(tmp_path, set())
        assert [f.name for f in files] == ["code.py"]


# =============================================================================
# Directory Scan Tests (parallel + sequential paths)
# =============================================================================

class TestScanDirectory:
    def test_sequential_and_parallel_agree(self, tmp_path: Path):
        """Both execution paths must produce identical block sets."""
        for i in range(25):
            d = tmp_path / f"d{i:02d}"
            d.mkdir()
            (d / "m.py").write_text(f"def func_{i}(a, b={i}):\n    return dict(v=a, w=b)")

        with config_override(parallel_min_files=100):  # force sequential
            seq = scan_directory(tmp_path)
        with config_override(parallel_min_files=5):  # force parallel
            par = scan_directory(tmp_path)

        seq_map = {(b.filepath.name, b.lineno): b.struct_hash for b in seq}
        par_map = {(b.filepath.name, b.lineno): b.struct_hash for b in par}
        assert seq_map == par_map
        assert len(seq) == 25

    def test_streaming_iter_matches_list(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def fa(): return 1")
        (tmp_path / "b.py").write_text("def fb(): return 2")
        streamed = list(iter_scan_directory(tmp_path))
        materialized = scan_directory(tmp_path)
        assert {b.struct_hash for b in streamed} == {b.struct_hash for b in materialized}

    def test_empty_directory(self, tmp_path: Path):
        assert scan_directory(tmp_path) == []

    def test_no_python_files(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("hi")
        assert scan_directory(tmp_path) == []

    def test_nonexistent_root(self, tmp_path: Path):
        assert scan_directory(tmp_path / "does_not_exist") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
