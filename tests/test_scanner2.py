"""
Tests for devdna.core.scanner2 (Optimized AST Scanner v2)

Run: pytest tests/test_scanner2.py -v
"""

import ast
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from devdna.core.scanner import extract_functions as extract_v1, scan_directory as scan_v1
from devdna.core.scanner2 import (
    FunctionExtractor,
    extract_functions as extract_v2,
    scan_directory as scan_v2,
    iter_scan_directory as scan_v2_iter,
    discover_python_files,
)


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


class TestKeywordArgRegression:
    """Test that keyword arguments in function calls don't crash unparse or lose values."""

    def test_keyword_args_normalization_parity(self, tmp_path):
        py_file = tmp_path / "kw_test.py"
        py_file.write_text('def foo(df):\n    return df.merge(left=df, how="inner")\n')

        blocks_v1 = extract_v1(py_file)
        blocks_v2 = extract_v2(py_file)

        assert len(blocks_v1) == 1
        assert len(blocks_v2) == 1
        assert blocks_v1[0].struct_hash == blocks_v2[0].struct_hash
        assert blocks_v1[0].func_name == blocks_v2[0].func_name == "foo"

    def test_type_annotations_preserved_in_hash(self, tmp_path):
        py_file1 = tmp_path / "ann1.py"
        py_file2 = tmp_path / "ann2.py"

        py_file1.write_text("def process(x: int) -> int:\n    return x + 1\n")
        py_file2.write_text("def process(x: str) -> str:\n    return x + 1\n")

        b1 = extract_v2(py_file1)[0]
        b2 = extract_v2(py_file2)[0]

        # Different type annotations should produce different normalized code/hashes
        assert b1.struct_hash != b2.struct_hash


class TestScannerV2Features:
    """Test AST traversal, single-pass node limit guard, and discovery."""

    def test_extract_simple_function(self, tmp_path):
        py_file = tmp_path / "simple.py"
        py_file.write_text("def add(a, b):\n    return a + b\n")

        blocks = extract_v2(py_file)
        assert len(blocks) == 1
        assert blocks[0].func_name == "add"
        assert blocks[0].lineno == 1

    def test_skip_pass_stub(self, tmp_path):
        py_file = tmp_path / "stub.py"
        py_file.write_text("def empty_func():\n    pass\n")

        blocks = extract_v2(py_file)
        assert len(blocks) == 0

    def test_skip_docstring_only_stub(self, tmp_path):
        py_file = tmp_path / "doc_stub.py"
        py_file.write_text('def doc_only():\n    """Only a docstring."""\n')

        blocks = extract_v2(py_file)
        assert len(blocks) == 0

    def test_skip_ellipsis_stub(self, tmp_path):
        py_file = tmp_path / "ellipsis.py"
        py_file.write_text("def protocol_method():\n    ...\n")

        blocks = extract_v2(py_file)
        assert len(blocks) == 0

    def test_flag_off_extracts_stubs(self, tmp_path):
        """skip_trivial_stubs=False restores raw extraction of stubs."""
        py_file = tmp_path / "stub.py"
        py_file.write_text("def empty_func():\n    pass\n")

        with config_override(skip_trivial_stubs=False):
            blocks = extract_v2(py_file)
        assert len(blocks) == 1

    def test_real_function_after_docstring_kept(self, tmp_path):
        """Docstring + real body must NOT be skipped as a stub."""
        py_file = tmp_path / "real.py"
        py_file.write_text('def compute(x):\n    """Docs."""\n    return x * 2\n')

        blocks = extract_v2(py_file)
        assert len(blocks) == 1

    def test_discover_python_files_prunes_excluded(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main(): pass")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("def lib(): pass")

        discovered = discover_python_files(tmp_path, exclude_patterns={".venv", "venv"})
        file_names = [p.name for p in discovered]

        assert "main.py" in file_names
        assert "lib.py" not in file_names


class TestV1V2HashParity:
    """Repo-wide structural hash parity check between v1 and v2 scanners."""

    def test_hash_parity_on_current_repo(self):
        root = Path(".")
        blocks_v1 = scan_v1(root)
        blocks_v2 = scan_v2(root)

        map_v1 = {(str(b.filepath), b.lineno): b for b in blocks_v1}
        map_v2 = {(str(b.filepath), b.lineno): b for b in blocks_v2}

        # Ensure both find functions
        assert len(map_v1) > 0
        assert len(map_v2) > 0

        common_keys = set(map_v1.keys()) & set(map_v2.keys())
        mismatches = []

        for k in common_keys:
            if map_v1[k].struct_hash != map_v2[k].struct_hash:
                # Compare ignoring decorator line differences
                n1 = [line for line in map_v1[k].normalized.splitlines() if not line.lstrip().startswith("@")]
                n2 = [line for line in map_v2[k].normalized.splitlines() if not line.lstrip().startswith("@")]
                if n1 != n2:
                    mismatches.append((k, n1, n2))

        assert len(mismatches) == 0, f"Found {len(mismatches)} unexplained structural hash mismatches between v1 and v2"


class TestAstGuardCounting:
    """Regression: guard must count each node accurately (no double count, no early abort)."""

    def test_node_count_matches_ast_walk(self):
        src = (
            "import os\n"
            "CONST = 42\n\n"
            "def outer(a: int, b='x') -> bool:\n"
            "    \"\"\"Doc.\"\"\"\n"
            "    def inner():\n"
            "        return dict(k=a)\n"
            "    for i in range(10):\n"
            "        if i > 2 and b:\n"
            "            yield inner()\n"
            "\n"
            "class Thing:\n"
            "    @property\n"
            "    def prop(self):\n"
            "        return [x * 2 for x in os.listdir()]\n"
        )
        tree = ast.parse(src)
        true_count = sum(1 for _ in ast.walk(tree))

        f = Path(tempfile.mkdtemp()) / "probe.py"
        f.write_text(src)
        ex = FunctionExtractor(src, f)
        ex.visit(tree)

        assert abs(ex._nodes_seen - true_count) <= 5

    def test_guard_trips_at_true_limit_not_half(self, tmp_path):
        """A file just under max_ast_nodes must NOT be aborted; one over must be."""
        body = "    x = 1\n"
        n_lines = 100
        src = "def fn():\n" + body * n_lines + "    return x\n"
        tree = ast.parse(src)
        exact = sum(1 for _ in ast.walk(tree))

        f = tmp_path / "sized.py"
        f.write_text(src)
        with config_override(max_ast_nodes=exact + 10):
            assert len(extract_v2(f)) == 1, "guard aborted a file AT the limit"
        with config_override(max_ast_nodes=exact - 10):
            assert extract_v2(f) == [], "guard accepted a file OVER the limit"


class TestDecoratorHandling:
    """Decorators are stripped from normalized output so the hash matches the
    stored source segment (get_source_segment excludes decorator lines)."""

    def test_decorated_hash_equals_undecorated_and_v1(self, tmp_path):
        d = tmp_path
        fd = d / "decorated.py"
        fp = d / "plain.py"
        fd.write_text("@app.route('/x')\n@cache\ndef handler(req):\n    return req.json()\n")
        fp.write_text("def handler(req):\n    return req.json()\n")

        b_dec = extract_v2(fd)[0]
        b_plain = extract_v2(fp)[0]
        b_v1 = extract_v1(fd)[0]

        assert "@" not in b_dec.normalized
        assert b_dec.struct_hash == b_plain.struct_hash == b_v1.struct_hash


class TestExecutionPaths:
    """Sequential and parallel execution must agree; streaming matches list."""

    def test_sequential_and_parallel_agree(self, tmp_path):
        for i in range(25):
            d = tmp_path / f"d{i:02d}"
            d.mkdir()
            (d / "m.py").write_text(f'def func_{i}(a, b={i}):\n    return dict(v=a, w=b)\n')

        with config_override(parallel_min_files=100):
            seq = scan_v2(tmp_path)
        with config_override(parallel_min_files=5):
            par = scan_v2(tmp_path)
        streamed = list(scan_v2_iter(tmp_path))

        key = lambda bs: {(b.filepath.name, b.lineno): b.struct_hash for b in bs}
        assert key(seq) == key(par) == key(streamed)
        assert len(seq) == 25

    def test_empty_and_missing_roots(self, tmp_path):
        assert scan_v2(tmp_path) == []
        assert scan_v2(tmp_path / "missing") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
