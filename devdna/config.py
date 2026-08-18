"""
Config — centralized configuration for DevDNA.

Loads from environment variables and .env file.
All settings have sensible defaults for MVP.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set, FrozenSet, Tuple

from dotenv import load_dotenv

# Load .env if present (no error if missing)
load_dotenv()


@dataclass(frozen=True)
class Config:
    """
    Immutable configuration for DevDNA.

    Usage:
        from devdna.config import config
        print(config.db_path)
    """

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    db_path: Path = field(
        default_factory=lambda: Path.home() / ".devdna" / "devdna.db"
    )
    sdk_output_dir: Path = field(
        default_factory=lambda: Path.home() / ".devdna" / "sdk"
    )

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------
    scan_root: Path = field(default_factory=lambda: Path("."))
    source_extensions: Tuple[str, ...] = ("*.py",)
    source_encoding: str = "utf-8"

    exclude_patterns: FrozenSet[str] = field(default_factory=lambda: frozenset({
        '.venv', 'venv', 'env', 'virtualenv',
        '__pycache__', '.pytest_cache', '.mypy_cache', '.tox', '.egg-info',
        '.git', '.hg', '.svn',
        'node_modules', 'vendor', '.bundle',
        '.idea', '.vscode', '.vim',
        'build', 'dist', 'target', 'out', 'site-packages',
        'docs/_build', '_build', 'htmlcov', '.coverage',
        '.env', '.env.local', '.env.dev', '.env.staging', '.env.production',
        '.envrc', '.flaskenv', '.djangoenv',
        'secrets', 'credentials', 'keys', 'private', '.ssh', '.gnupg',
        'fixtures', 'testdata', 'test_data', 'sample_data',
        'tmp', 'temp', '.tmp', '.temp', 'cache', '.cache',
        '.DS_Store', 'Thumbs.db', 'desktop.ini',
        'logs', 'log',
        '.github', '.gitlab-ci', '.circleci',
    }))

    struct_hash_length: int = 16

    normalization_tokens: dict[str, str] = field(default_factory=lambda: {
        "name": "VAR",
        "arg": "ARG",
        "keyword": "VAR",
        "func_name": "FUNC",
        "string": "STR",
        "number": "0",
    })

    # ------------------------------------------------------------------
    # Analyzer
    # ------------------------------------------------------------------
    min_cluster_size: int = 2
    max_clusters: int = 50

    # (min_occurrences, min_unique_files)
    high_confidence_threshold: Tuple[int, int] = (10, 5)
    medium_confidence_threshold: Tuple[int, int] = (5, 3)

    # ------------------------------------------------------------------
    # LLM Bridge
    # ------------------------------------------------------------------
    anthropic_api_key: Optional[str] = None
    llm_model: str = "claude-sonnet-4-20250514"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    # ------------------------------------------------------------------
    # Generator
    # ------------------------------------------------------------------
    default_package_name: str = "devdna_sdk"
    default_version: str = "0.1.0"

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    db_file_permissions: int = 0o600  # Not enforced on Windows
    max_file_size_bytes: int = 5 * 1024 * 1024  # 5 MB
    max_ast_nodes: int = 50_000

    # ------------------------------------------------------------------
    # Post-MVP placeholders
    # ------------------------------------------------------------------
    comment_strip_patterns: Tuple[str, ...] = (
        r"#.*",           # inline comments
        r"\"\"\"[\s\S]*?\"\"\"",  # docstrings
        r"'''[\s\S]*?'''",         # docstrings
    )

    def __post_init__(self) -> None:
        # Resolve API key from env if not provided
        if self.anthropic_api_key is None:
            object.__setattr__(
                self, "anthropic_api_key", os.getenv("ANTHROPIC_API_KEY")
            )


# Singleton instance — import this everywhere
config = Config()