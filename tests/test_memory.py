"""
Tests for devdna.core.memory

Run: pytest tests/test_memory.py -v

Uses in-memory SQLite for speed and isolation.
"""

from pathlib import Path

import pytest

from devdna.core.memory import MemoryStore, StoredPattern


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def store(tmp_path):
    """Fresh in-memory store for each test."""
    db = tmp_path / "test.db"
    return MemoryStore(db_path=db)


@pytest.fixture
def sample_proposal():
    """Valid proposal dict."""
    return {
        "function_name": "retry_request",
        "signature": "def retry_request(url: str) -> Response:",
        "implementation": "def retry_request(url: str) -> Response:\n    pass",
        "source_hash": "abc123def456",
        "example_count": 5,
        "suggested_module": "api_client",
        "description": "Retries HTTP requests",
        "confidence_reasoning": "Strong pattern",
    }


# =============================================================================
# Schema Tests
# =============================================================================

class TestSchema:
    """Database initialization tests."""

    def test_creates_db_file(self, tmp_path):
        """Store creation makes the DB file."""
        db = tmp_path / "new.db"
        assert not db.exists()
        MemoryStore(db_path=db)
        assert db.exists()

    def test_creates_tables(self, store):
        """Tables exist after init."""
        with sqlite3.connect(store.db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            names = {t[0] for t in tables}
            assert "patterns" in names
            assert "sync_history" in names


# =============================================================================
# save_proposal Tests
# =============================================================================

class TestSaveProposal:
    """Tests for proposal insertion."""

    def test_saves_valid_proposal(self, store, sample_proposal):
        """Returns row ID on success."""
        pid = store.save_proposal(sample_proposal)
        assert isinstance(pid, int)
        assert pid > 0

    def test_skips_duplicate_hash(self, store, sample_proposal):
        """Same source_hash = None on second insert."""
        pid1 = store.save_proposal(sample_proposal)
        assert pid1 is not None
        pid2 = store.save_proposal(sample_proposal)
        assert pid2 is None

    def test_raises_on_missing_required_field(self, store):
        """Missing function_name raises ValueError."""
        bad = {"signature": "def foo():", "implementation": "pass", "source_hash": "x", "example_count": 1}
        with pytest.raises(ValueError, match="missing required fields"):
            store.save_proposal(bad)

    def test_raises_on_empty_function_name(self, store, sample_proposal):
        """Empty function_name raises ValueError."""
        sample_proposal["function_name"] = ""
        with pytest.raises(ValueError, match="cannot be empty"):
            store.save_proposal(sample_proposal)

    def test_raises_on_negative_example_count(self, store, sample_proposal):
        """Negative count raises ValueError."""
        sample_proposal["example_count"] = -1
        with pytest.raises(ValueError, match="non-negative"):
            store.save_proposal(sample_proposal)

    def test_uses_default_module(self, store, sample_proposal):
        """Missing suggested_module defaults to 'utils'."""
        del sample_proposal["suggested_module"]
        pid = store.save_proposal(sample_proposal)
        row = store.get_pending(limit=1)[0]
        assert row.suggested_module == "utils"


# =============================================================================
# Query Tests
# =============================================================================

class TestQueries:
    """Tests for retrieval methods."""

    def test_get_pending_empty(self, store):
        """No patterns = empty list."""
        assert store.get_pending() == []

    def test_get_pending_returns_only_proposed(self, store, sample_proposal):
        """Filters by status correctly."""
        store.save_proposal(sample_proposal)
        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].status == "proposed"

    def test_get_accepted_empty_initially(self, store, sample_proposal):
        """No accepted patterns yet."""
        store.save_proposal(sample_proposal)
        assert store.get_accepted() == []

    def test_get_by_status_invalid(self, store):
        """Invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            store.get_by_status("invalid")

    def test_get_by_status_limit(self, store, sample_proposal):
        """Limit restricts results."""
        for i in range(5):
            p = dict(sample_proposal)
            p["source_hash"] = f"hash{i}"
            store.save_proposal(p)
        assert len(store.get_pending(limit=3)) == 3
        assert len(store.get_pending(limit=10)) == 5


# =============================================================================
# Status Transition Tests
# =============================================================================

class TestStatusTransitions:
    """Tests for accept/reject/update_status."""

    def test_accept_returns_tuple(self, store, sample_proposal):
        """Returns (bool, str)."""
        pid = store.save_proposal(sample_proposal)
        ok, msg = store.accept(pid)
        assert ok is True
        assert isinstance(msg, str)
        assert "retry_request" in msg

    def test_reject_returns_tuple(self, store, sample_proposal):
        """Returns (bool, str)."""
        pid = store.save_proposal(sample_proposal)
        ok, msg = store.reject(pid)
        assert ok is True
        assert "rejected" in msg.lower()

    def test_accept_changes_status(self, store, sample_proposal):
        """Pattern moves from proposed to accepted."""
        pid = store.save_proposal(sample_proposal)
        store.accept(pid)
        accepted = store.get_accepted()
        assert len(accepted) == 1
        assert accepted[0].status == "accepted"
        assert accepted[0].reviewed_at is not None

    def test_reject_removes_from_pending(self, store, sample_proposal):
        """Rejected pattern no longer in pending."""
        pid = store.save_proposal(sample_proposal)
        store.reject(pid)
        assert store.get_pending() == []

    def test_invalid_id_returns_false(self, store):
        """Non-existent ID returns (False, message)."""
        ok, msg = store.accept(99999)
        assert ok is False
        assert "not found" in msg

    def test_cannot_set_proposed_manually(self, store, sample_proposal):
        """update_status to 'proposed' is blocked."""
        pid = store.save_proposal(sample_proposal)
        ok, msg = store.update_status(pid, "proposed")
        assert ok is False
        assert "Cannot manually" in msg

    def test_invalid_status_returns_false(self, store, sample_proposal):
        """Unknown status returns (False, message)."""
        pid = store.save_proposal(sample_proposal)
        ok, msg = store.update_status(pid, "deleted")
        assert ok is False
        assert "Invalid status" in msg


# =============================================================================
# Sync History Tests
# =============================================================================

class TestSyncHistory:
    """Tests for audit trail."""

    def test_log_sync_start_returns_id(self, store):
        """Returns integer sync ID."""
        sid = store.log_sync_start(Path("/test"))
        assert isinstance(sid, int)
        assert sid > 0

    def test_log_sync_complete_success(self, store):
        """Returns (True, message) on valid ID."""
        sid = store.log_sync_start(Path("/test"))
        ok, msg = store.log_sync_complete(sid, 10, 3, 2)
        assert ok is True
        assert str(sid) in msg
        assert "10 functions" in msg

    def test_log_sync_complete_invalid_id(self, store):
        """Returns (False, warning) on bad ID."""
        ok, msg = store.log_sync_complete(99999, 0, 0, 0)
        assert ok is False
        assert "not found" in msg

    def test_get_recent_syncs(self, store):
        """Returns sync history ordered by time."""
        sid1 = store.log_sync_start(Path("/a"))
        store.log_sync_complete(sid1, 5, 2, 1)
        sid2 = store.log_sync_start(Path("/b"))
        store.log_sync_complete(sid2, 10, 4, 3)

        recent = store.get_recent_syncs(limit=5)
        assert len(recent) == 2
        assert recent[0]["root_path"] == "/b"  # newest first


# =============================================================================
# Stats Tests
# =============================================================================

class TestStats:
    """Tests for aggregate statistics."""

    def test_empty_stats(self, store):
        """All zeros when no patterns."""
        stats = store.get_stats()
        assert stats == {
            "total_patterns": 0,
            "pending": 0,
            "accepted": 0,
            "rejected": 0,
        }

    def test_stats_after_operations(self, store, sample_proposal):
        """Counts reflect current state."""
        p1 = dict(sample_proposal)
        p2 = dict(sample_proposal)
        p2["source_hash"] = "different"
        p2["function_name"] = "other"

        pid1 = store.save_proposal(p1)
        pid2 = store.save_proposal(p2)
        store.accept(pid1)
        store.reject(pid2)

        stats = store.get_stats()
        assert stats["total_patterns"] == 2
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1
        assert stats["pending"] == 0


# Need to import sqlite3 for schema test
import sqlite3