"""
Tests for devdna.core.generator

Run: pytest tests/test_generator.py -v
"""

from pathlib import Path

import pytest

from devdna.core.generator import SDKGenerator
from devdna.core.memory import StoredPattern


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_patterns():
    """List of accepted StoredPattern objects."""
    return [
        StoredPattern(
            id=1,
            function_name="retry_request",
            signature="def retry_request(url: str) -> Response:",
            implementation='def retry_request(url: str) -> Response:\n    """Retry with backoff."""\n    pass',
            suggested_module="api_client",
            description="Retries HTTP requests",
            confidence_reasoning="Strong",
            source_hash="abc123",
            example_count=5,
            status="accepted",
            created_at="2026-08-06T00:00:00+00:00",
            reviewed_at="2026-08-06T00:00:00+00:00",
        ),
        StoredPattern(
            id=2,
            function_name="clean_dataframe",
            signature="def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:",
            implementation="def clean_dataframe(df):\n    return df.dropna()",
            suggested_module="data_utils",
            description="Drop null values",
            confidence_reasoning="Common",
            source_hash="def456",
            example_count=3,
            status="accepted",
            created_at="2026-08-06T00:00:00+00:00",
            reviewed_at="2026-08-06T00:00:00+00:00",
        ),
        StoredPattern(
            id=3,
            function_name="setup_logger",
            signature="def setup_logger(name: str) -> Logger:",
            implementation="def setup_logger(name):\n    return logging.getLogger(name)",
            suggested_module="api_client",  # same module as #1
            description="Create logger",
            confidence_reasoning="Weak",
            source_hash="ghi789",
            example_count=2,
            status="accepted",
            created_at="2026-08-06T00:00:00+00:00",
            reviewed_at="2026-08-06T00:00:00+00:00",
        ),
    ]


# =============================================================================
# Generation Tests
# =============================================================================

class TestGenerate:
    """Tests for SDK package generation."""

    def test_creates_output_directory(self, tmp_path, sample_patterns):
        """generate() creates the output directory."""
        gen = SDKGenerator(package_name="test_sdk", output_dir=tmp_path / "out")
        path = gen.generate(sample_patterns)
        assert path.exists()

    def test_creates_pyproject_toml(self, tmp_path, sample_patterns):
        """pyproject.toml exists and contains package name."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        toml = (tmp_path / "out" / "pyproject.toml").read_text()
        assert 'name = "my_sdk"' in toml
        assert "hatchling" in toml

    def test_creates_readme(self, tmp_path, sample_patterns):
        """README.md exists with module docs."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        readme = (tmp_path / "out" / "README.md").read_text()
        assert "my_sdk" in readme
        assert "api_client" in readme
        assert "retry_request" in readme

    def test_creates_package_directory(self, tmp_path, sample_patterns):
        """Package folder exists inside output."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        pkg_dir = tmp_path / "out" / "my_sdk"
        assert pkg_dir.exists()
        assert (pkg_dir / "__init__.py").exists()

    def test_creates_module_files(self, tmp_path, sample_patterns):
        """One .py file per suggested_module."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        pkg_dir = tmp_path / "out" / "my_sdk"
        assert (pkg_dir / "api_client.py").exists()
        assert (pkg_dir / "data_utils.py").exists()

    def test_module_contains_implementation(self, tmp_path, sample_patterns):
        """Module files contain the actual function code."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        api = (tmp_path / "out" / "my_sdk" / "api_client.py").read_text()
        assert "retry_request" in api
        assert "setup_logger" in api

    def test_init_contains_exports(self, tmp_path, sample_patterns):
        """__init__.py exports all function names."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        init = (tmp_path / "out" / "my_sdk" / "__init__.py").read_text()
        assert "retry_request" in init
        assert "clean_dataframe" in init
        assert "setup_logger" in init
        assert "__all__" in init

    def test_init_exports_are_unique(self, tmp_path, sample_patterns):
        """No duplicate exports in __all__."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        init = (tmp_path / "out" / "my_sdk" / "__init__.py").read_text()
        # Check that __all__ list has no duplicates
        # This is a basic sanity check
        assert init.count('"retry_request"') == 1

    def test_raises_on_empty_patterns(self, tmp_path):
        """Empty patterns list raises ValueError."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        with pytest.raises(ValueError, match="No accepted patterns"):
            gen.generate([])

    def test_sanitizes_module_names(self, tmp_path, sample_patterns):
        """Weird module names become valid Python identifiers."""
        sample_patterns[0].suggested_module = "API-Client!!"
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        pkg_dir = tmp_path / "out" / "my_sdk"
        assert (pkg_dir / "api_client.py").exists()

    def test_idempotent_regeneration(self, tmp_path, sample_patterns):
        """Running twice overwrites cleanly."""
        gen = SDKGenerator(package_name="my_sdk", output_dir=tmp_path / "out")
        gen.generate(sample_patterns)
        gen.generate(sample_patterns)
        # Should not crash, should produce same structure
        assert (tmp_path / "out" / "my_sdk" / "__init__.py").exists()


# =============================================================================
# Sanitize Tests
# =============================================================================

class TestSanitizeModule:
    """Tests for _sanitize_module."""

    def test_lowercases(self):
        assert SDKGenerator._sanitize_module("FooBar") == "foobar"

    def test_replaces_hyphens(self):
        assert SDKGenerator._sanitize_module("foo-bar") == "foo_bar"

    def test_replaces_spaces(self):
        assert SDKGenerator._sanitize_module("foo bar") == "foo_bar"

    def test_replaces_dots(self):
        assert SDKGenerator._sanitize_module("foo.bar") == "foo_bar"

    def test_removes_special_chars(self):
        assert SDKGenerator._sanitize_module("foo@bar#baz") == "foo_bar_baz"

    def test_collapses_underscores(self):
        assert SDKGenerator._sanitize_module("foo__bar") == "foo_bar"

    def test_strips_leading_trailing_underscores(self):
        assert SDKGenerator._sanitize_module("_foo_") == "foo"

    def test_empty_string(self):
        assert SDKGenerator._sanitize_module("") == ""

    def test_only_special_chars(self):
        assert SDKGenerator._sanitize_module("!!!") == ""


#ALL PASSED