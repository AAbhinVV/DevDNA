"""
Tests for devdna.core.scanner

Run: pytest tests/test_scanner.py -v
"""

import ast
import sys
import tempfile
from pathlib import Path

import pytest

from devdna.core.scanner import CodeBlock, scan_directory, extract_functions, DEFAULT_EXCLUDE_PATTERNS


# =============================================================================
# CodeBlock Tests
# =============================================================================

class TestCodeBlock:
    """Unit tests for the CodeBlock value object."""

    def test_codeblock_creation(self):
        """CodeBlock stores all attributes correctly."""
        block = CodeBlock(
            source_code="def foo(x):\n    return x + 1",
            filepath=Path("test.py"),
            func_name="foo",
            lineno=5,
        )
        assert block.func_name == "foo"
        assert block.lineno == 5
        assert block.filepath.name == "test.py"
        assert block.source_code == "def foo(x):\n    return x + 1"

    def test_normalization_replaces_variables(self):
        """Variable names become VAR."""
        block = CodeBlock(
            source_code="def foo(dataframe):\n    return dataframe.dropna()",
            filepath=Path("a.py"),
            func_name="foo",
            lineno=1,
        )
        assert "VAR" in block.normalized
        assert "dataframe" not in block.normalized

    def test_normalization_replaces_strings(self):
        """String literals become STR."""
        block = CodeBlock(
            source_code='def foo():\n    return "hello"',
            filepath=Path("a.py"),
            func_name="foo",
            lineno=1,
        )
        assert "STR" in block.normalized
        assert "hello" not in block.normalized

    def test_normalization_replaces_numbers(self):
        """Numeric constants become 0."""
        block = CodeBlock(
            source_code="def foo():\n    return 42",
            filepath=Path("a.py"),
            func_name="foo",
            lineno=1,
        )
        assert "0" in block.normalized
        assert "42" not in block.normalized

    def test_struct_hash_consistency(self):
        """Same structure = same hash."""
        b1 = CodeBlock(
            source_code="def a(x): return x + 1",
            filepath=Path("f1.py"),
            func_name="a",
            lineno=1,
        )
        b2 = CodeBlock(
            source_code="def b(y): return y + 1",
            filepath=Path("f2.py"),
            func_name="b",
            lineno=1,
        )
        assert b1.struct_hash == b2.struct_hash
        assert len(b1.struct_hash) == 16  # truncated SHA-256

    def test_struct_hash_uniqueness(self):
        """Different structures = different hashes."""
        b1 = CodeBlock(
            source_code="def a(x): return x + 1",
            filepath=Path("f1.py"),
            func_name="a",
            lineno=1,
        )
        b2 = CodeBlock(
            source_code="def a(x): return x * 2",
            filepath=Path("f2.py"),
            func_name="a",
            lineno=1,
        )
        assert b1.struct_hash != b2.struct_hash

    def test_normalization_empty_on_syntax_error(self):
        """Invalid Python returns empty normalized string."""
        block = CodeBlock(
            source_code="def broken(:",
            filepath=Path("bad.py"),
            func_name="broken",
            lineno=1,
        )
        assert block.normalized == ""
        assert block.struct_hash != ""  # hash of empty string is still a hash

    def test_repr_format(self):
        """repr is informative."""
        block = CodeBlock(
            source_code="def foo(): pass",
            filepath=Path("/path/to/file.py"),
            func_name="foo",
            lineno=10,
        )
        r = repr(block)
        assert "foo" in r
        assert "file.py" in r
        assert "10" in r


# =============================================================================
# extract_functions Tests
# =============================================================================

class TestExtractFunctions:
    """Tests for single-file function extraction."""

    def test_extracts_simple_function(self, tmp_path: Path):
        """Basic function definition."""
        f = tmp_path / "simple.py"
        f.write_text("def hello():\n    pass")
        blocks = extract_functions(f)
        assert len(blocks) == 1
        assert blocks[0].func_name == "hello"

    def test_extracts_multiple_functions(self, tmp_path: Path):
        """Multiple functions in one file."""
        f = tmp_path / "multi.py"
        f.write_text("def a(): pass\ndef b(): pass\ndef c(): pass")
        blocks = extract_functions(f)
        assert len(blocks) == 3
        names = {b.func_name for b in blocks}
        assert names == {"a", "b", "c"}

    def test_skips_nested_functions(self, tmp_path: Path):
        """Nested functions are extracted by ast.walk — verify behavior."""
        f = tmp_path / "nested.py"
        f.write_text("def outer():\n    def inner(): pass")
        blocks = extract_functions(f)
        # ast.walk finds both outer and inner — this is current behavior
        # Document whether this is intended or a known limitation
        assert len(blocks) == 2

    def test_skips_non_function_defs(self, tmp_path: Path):
        """Classes are not extracted (only FunctionDef)."""
        f = tmp_path / "classy.py"
        f.write_text("class Foo:\n    def method(self): pass")
        blocks = extract_functions(f)
        # Currently only FunctionDef, not AsyncFunctionDef or classes
        # method IS a FunctionDef inside a ClassDef, so ast.walk finds it
        assert len(blocks) == 1
        assert blocks[0].func_name == "method"

    def test_handles_empty_file(self, tmp_path: Path):
        """Empty file returns empty list."""
        f = tmp_path / "empty.py"
        f.write_text("")
        blocks = extract_functions(f)
        assert blocks == []

    def test_handles_syntax_error(self, tmp_path: Path):
        """Syntax error returns empty list, no crash."""
        f = tmp_path / "broken.py"
        f.write_text("def broken(:")
        blocks = extract_functions(f)
        assert blocks == []

    def test_preserves_lineno(self, tmp_path: Path):
        """Line numbers are accurate."""
        f = tmp_path / "lines.py"
        f.write_text("# comment\n\ndef foo():\n    pass")
        blocks = extract_functions(f)
        assert blocks[0].lineno == 3

    def test_permission_error_handling(self, tmp_path: Path):
        if sys.platform == "win32":
            pytest.skip("Windows doesn't support Unix-style permission denial")
        
        f = tmp_path / "secret.py"
        f.write_text("def foo(): pass")
        f.chmod(0o000)
        try:
            blocks = extract_functions(f)
            assert blocks == []
        finally:
            f.chmod(0o644) # cleanup


# =============================================================================
# scan_directory Tests
# =============================================================================

class TestScanDirectory:
    """Tests for recursive directory scanning."""

    def test_finds_python_files(self, tmp_path: Path):
        """Discovers .py files recursively."""
        (tmp_path / "a.py").write_text("def f1(): pass")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("def f2(): pass")
        blocks = scan_directory(tmp_path)
        assert len(blocks) == 2

    def test_excludes_venv(self, tmp_path: Path):
        """venv directory is skipped."""
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "site.py").write_text("def fake(): pass")
        (tmp_path / "real.py").write_text("def real(): pass")
        blocks = scan_directory(tmp_path)
        assert len(blocks) == 1
        assert blocks[0].func_name == "real"

    def test_excludes_pycache(self, tmp_path: Path):
        """__pycache__ is skipped."""
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.py").write_text("def cached(): pass")
        blocks = scan_directory(tmp_path)
        assert len(blocks) == 0

    def test_excludes_hidden_files(self, tmp_path: Path):
        """Hidden files (starting with .) are skipped."""
        (tmp_path / ".secret.py").write_text("def secret(): pass")
        blocks = scan_directory(tmp_path)
        assert len(blocks) == 0

    def test_respects_custom_exclude(self, tmp_path: Path):
        """Custom exclusion patterns work."""
        (tmp_path / "custom_skip").mkdir()
        (tmp_path / "custom_skip" / "a.py").write_text("def a(): pass")
        (tmp_path / "keep").mkdir()
        (tmp_path / "keep" / "b.py").write_text("def b(): pass")
        blocks = scan_directory(tmp_path, exclude_patterns={"custom_skip"})
        assert len(blocks) == 1
        assert blocks[0].func_name == "b"

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory returns empty list."""
        blocks = scan_directory(tmp_path)
        assert blocks == []

    def test_no_python_files(self, tmp_path: Path):
        """Directory with no .py files returns empty list."""
        (tmp_path / "readme.txt").write_text("hello")
        blocks = scan_directory(tmp_path)
        assert blocks == []


# =============================================================================
# DEFAULT_EXCLUDE_PATTERNS Tests
# =============================================================================

class TestExcludePatterns:
    """Sanity checks on the exclusion list."""

    def test_common_venvs_present(self):
        """venv variants are excluded."""
        assert ".venv" in DEFAULT_EXCLUDE_PATTERNS
        assert "venv" in DEFAULT_EXCLUDE_PATTERNS
        assert "env" in DEFAULT_EXCLUDE_PATTERNS

    def test_secrets_excluded(self):
        """Secret directories are excluded."""
        assert ".env" in DEFAULT_EXCLUDE_PATTERNS
        assert "secrets" in DEFAULT_EXCLUDE_PATTERNS

    def test_no_empty_strings(self):
        """No accidental empty patterns that would match everything."""
        assert "" not in DEFAULT_EXCLUDE_PATTERNS

#ALL PASSED