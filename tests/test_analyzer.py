"""
Tests for devdna.core.analyzer

Run: pytest tests/test_analyzer.py -v
"""

from pathlib import Path

import pytest

from devdna.core.analyzer import (
    PatternCluster,
    cluster_by_structure,
    analyze_patterns,
    get_cluster_stats,
)
from devdna.core.scanner import CodeBlock


# =============================================================================
# PatternCluster Tests
# =============================================================================

class TestPatternCluster:
    """Unit tests for PatternCluster."""

    def test_empty_cluster_is_low_confidence(self):
        """Fresh cluster has Low confidence."""
        c = PatternCluster("abc123")
        assert c.confidence_label == "Low"
        assert c.confidence_score == 0.0

    def test_add_increments_count(self):
        """Adding blocks increases count."""
        c = PatternCluster("abc123")
        block = CodeBlock("def f(): pass", Path("a.py"), "f", 1)
        c.add(block)
        assert c.source_count == 1
        assert len(c) == 1

    def test_medium_confidence_threshold(self):
        """5 blocks across 3 files = Medium."""
        c = PatternCluster("abc123")
        for i in range(5):
            c.add(CodeBlock("def f(): pass", Path(f"file{i%3}.py"), "f", 1))
        assert c.confidence_label == "Medium"
        assert c.confidence_score == 0.6

    def test_high_confidence_threshold(self):
        """10 blocks across 5 files = High."""
        c = PatternCluster("abc123")
        for i in range(10):
            c.add(CodeBlock("def f(): pass", Path(f"file{i%5}.py"), "f", 1))
        assert c.confidence_label == "High"
        assert c.confidence_score == 0.9

    def test_unique_file_count(self):
        """Same file repeated doesn't inflate unique count."""
        c = PatternCluster("abc123")
        for _ in range(5):
            c.add(CodeBlock("def f(): pass", Path("same.py"), "f", 1))
        assert c.unique_file_count == 1
        assert c.confidence_label == "Low"

    def test_top_examples_returns_n(self):
        """top_examples(n) respects the limit."""
        c = PatternCluster("abc123")
        for i in range(5):
            c.add(CodeBlock(f"def f{i}(): pass", Path(f"{i}.py"), f"f{i}", 1))
        assert len(c.top_examples(3)) == 3
        assert len(c.top_examples(10)) == 5

    def test_top_examples_empty_cluster(self):
        """Empty cluster returns empty list."""
        c = PatternCluster("abc123")
        assert c.top_examples(3) == []

    def test_repr_contains_key_info(self):
        """repr is informative."""
        c = PatternCluster("abc123")
        c.add(CodeBlock("def f(): pass", Path("a.py"), "f", 1))
        r = repr(c)
        assert "PatternCluster" in r
        assert "abc123" in r or "abc" in r


# =============================================================================
# cluster_by_structure Tests
# =============================================================================

class TestClusterByStructure:
    """Tests for the core clustering algorithm."""

    def test_groups_identical_structures(self):
        """Same hash = same cluster."""
        b1 = CodeBlock("def a(x): return x + 1", Path("f1.py"), "a", 1)
        b2 = CodeBlock("def b(y): return y + 1", Path("f2.py"), "b", 1)
        clusters = cluster_by_structure([b1, b2], min_cluster_size=2)
        assert len(clusters) == 1
        assert clusters[0].source_count == 2

    def test_different_structures_separate_clusters(self):
        """Different hashes = different clusters."""
        b1 = CodeBlock("def a(x): return x + 1", Path("f1.py"), "a", 1)
        b2 = CodeBlock("def b(x): return x * 2", Path("f2.py"), "b", 1)
        clusters = cluster_by_structure([b1, b2], min_cluster_size=1)
        assert len(clusters) == 2

    def test_min_cluster_size_filter(self):
        """Clusters below threshold are dropped."""
        b1 = CodeBlock("def a(x): return x + 1", Path("f1.py"), "a", 1)
        b2 = CodeBlock("def b(x): return x + 1", Path("f2.py"), "b", 1)
        b3 = CodeBlock("def c(x): return x * 2", Path("f3.py"), "c", 1)
        clusters = cluster_by_structure([b1, b2, b3], min_cluster_size=2)
        assert len(clusters) == 1  # only the +1 pattern has 2 members

    def test_empty_input(self):
        """Empty list returns empty list."""
        clusters = cluster_by_structure([], min_cluster_size=2)
        assert clusters == []

    def test_single_block(self):
        """One block below threshold = empty."""
        b = CodeBlock("def a(): pass", Path("a.py"), "a", 1)
        clusters = cluster_by_structure([b], min_cluster_size=2)
        assert clusters == []

    def test_sorting_high_first(self):
        """High confidence clusters come first."""
        # Low confidence cluster (2 blocks, 1 file) — different structure
        low = [CodeBlock("def f(): return 0", Path("a.py"), "f", 1) for _ in range(2)]
        # High confidence cluster (10 blocks, 5 files) — different structure
        high = [CodeBlock("def g(): pass", Path(f"{i%5}.py"), "g", 1) for i in range(10)]
        clusters = cluster_by_structure(low + high, min_cluster_size=2)
        assert len(clusters) == 2
        assert clusters[0].confidence_label == "High"
        assert clusters[1].confidence_label == "Low"

    def test_skips_empty_hashes(self):
        """Blocks with empty normalized/hash are skipped."""
        bad = CodeBlock("def broken(:", Path("bad.py"), "broken", 1)
        good = CodeBlock("def ok(): pass", Path("good.py"), "ok", 1)
        assert bad.normalized == ""  # from syntax error
        clusters = cluster_by_structure([bad, good, good], min_cluster_size=2)
        assert len(clusters) == 1
        assert clusters[0].source_count == 2


# =============================================================================
# analyze_patterns Tests
# =============================================================================

class TestAnalyzePatterns:
    """Tests for the high-level analysis entry point."""

    def test_returns_limited_clusters(self):
        """max_clusters limits output."""
        blocks = [
            CodeBlock(f"def f{i}(): return x + {i}", Path(f"{i}.py"), f"f{i}", 1)
            for i in range(100)
        ]
        clusters = analyze_patterns(blocks, min_cluster_size=1, max_cluster=5)
        assert len(clusters) <= 5

    def test_filters_by_min_cluster_size(self):
        """min_cluster_size is respected."""
        b1 = CodeBlock("def a(): pass", Path("a.py"), "a", 1)
        b2 = CodeBlock("def b(): pass", Path("b.py"), "b", 1)
        b3 = CodeBlock("def c(): return 1", Path("c.py"), "c", 1)
        clusters = analyze_patterns([b1, b2, b3], min_cluster_size=2, max_cluster=50)
        # a and b are identical structure, c is alone
        assert len(clusters) == 1


# =============================================================================
# get_cluster_stats Tests
# =============================================================================

class TestGetClusterStats:
    """Tests for statistics aggregation."""

    def test_empty_clusters(self):
        """Empty list returns zeros."""
        stats = get_cluster_stats([])
        assert stats["total_clusters"] == 0
        assert stats["high_confidence"] == 0
        assert stats["total_blocks"] == 0

    def test_counts_by_confidence(self):
        """Correctly buckets by confidence."""
        high = PatternCluster("h")
        for i in range(10):
            high.add(CodeBlock("def f(): pass", Path(f"{i%5}.py"), "f", 1))

        med = PatternCluster("m")
        for i in range(5):
            med.add(CodeBlock("def g(): pass", Path(f"{i%3}.py"), "g", 1))

        low = PatternCluster("l")
        low.add(CodeBlock("def h(): pass", Path("a.py"), "h", 1))
        low.add(CodeBlock("def i(): pass", Path("b.py"), "i", 1))

        stats = get_cluster_stats([high, med, low])
        assert stats["total_clusters"] == 3
        assert stats["high_confidence"] == 1
        assert stats["medium_confidence"] == 1
        assert stats["low_confidence"] == 1
        assert stats["total_blocks"] == 17