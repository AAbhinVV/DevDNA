'''
Dict intput
parametrized queries
skip duplicates(source_hash comparison)
timestamps
SQLITE persistance layer
never delete proposals, change status
sync history logs every run
timestamps on every record
'''

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass
class StoredPattern:
    id: int
    function_name: str
    signature: str
    implementation: str
    suggested_module: str
    description: str
    confidence_reasoning: str
    source_hash: str
    example_count: int
    status: str
    created_at: str
    reviewed_at: Optional[str]

class MemoryStore:
    """
    SQLite-backed store for pattern proposals and sync history.

    Usage:
        store = MemoryStore()
        pid = store.save_proposal({...})
        pending = store.get_pending(limit=10)
        store.accept(pid)
    """

    STATUSES = ("proposed", "accepted", "rejected")

    def __init__(self, dbPath: Optional[Path] = None) -> None:
        if dbPath is None:
            dbPath = Path.home() / ".devdna" / "devdna.db"

        self.dbPath = dbPath
        self.dbPath.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.dbPath) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    function_name TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    implementation TEXT NOT NULL,
                    suggested_module TEXT NOT NULL DEFAULT 'utils',
                    description TEXT,
                    confidence_reasoning TEXT,
                    source_hash TEXT NOT NULL,
                    example_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                        CHECK(status IN ('proposed', 'accepted', 'rejected')),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    reviewed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root_path TEXT NOT NULL,
                    functions_found INTEGER NOT NULL DEFAULT 0,
                    patterns_detected INTEGER NOT NULL DEFAULT 0,
                    proposals_generated INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_patterns_status
                    ON patterns(status);
                CREATE INDEX IF NOT EXISTS idx_patterns_hash
                    ON patterns(source_hash);
                CREATE INDEX IF NOT EXISTS idx_patterns_created
                    ON patterns(created_at);
                """
            )
            conn.commit()


    def save_proposal(self, proposal: Dict[str, Any], skip_duplicates: bool = True) -> Optional[int]:
        """
        Save a new pattern proposal to the database.
        Returns the ID of the inserted record.
        """
        required = {
            "function_name",
            "signature",
            "implementation",
            "source_hash",
            "example_count",
        }

        if not proposal.get("function_name", "").strip():
            raise ValueError("function_name cannot be empty")

        missing = required - set(proposal.keys())
        if missing:
            raise ValueError(f"missing required fields")

        if skip_duplicates and self._hash_exists(proposal["source_hash"]):
            return None

        if not isinstance(proposal.get("example_count", 0), int) or proposal["example_count"] < 0:
            raise ValueError("example_count must be a non-negative integer")

        sql = """
            INSERT INTO patterns (
                function_name, signature, implementation, suggested_module,
                description, confidence_reasoning, source_hash, example_count,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            proposal["function_name"],
            proposal["signature"],
            proposal["implementation"],
            proposal.get("suggested_module", "utils"),
            proposal.get("description", ""),
            proposal.get("confidence_reasoning", ""),
            proposal["source_hash"],
            proposal["example_count"],
            "proposed",
            self._now(),
        )

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.lastrowid

    def _hash_exists(self, source_hash: str) -> bool:
        sql = "SELECT 1 FROM patterns WHERE source_hash = ? LIMIT 1"
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.execute(sql, (source_hash,)).fetchone()
            return cursor is not None

    def get_by_status(self, status: str, limit: int = 100, order_by: str = "created_at_DESC") -> List[StoredPattern]:
        #limti max rows to return
        if status not in self.STATUSES:
            raise ValueError(f"Invalid status: {status}, use one of {self.STATUSES}")

        allowed_orders = {
            "created_at DESC": "created_at DESC",
            "created_at ASC": "created_at ASC",
            "example_count DESC": "example_count DESC",
        }

        order_clause = allowed_orders.get(order_by, "created_at DESC")
        sql = f"""
            SELECT
                id, function_name, signature, implementation,
                suggested_module, description, confidence_reasoning,
                source_hash, example_count, status, created_at, reviewed_at
            FROM patterns
            WHERE status = ?
            ORDER BY {order_clause}
            LIMIT ?
        """

        with sqlite3.connect(self.dbPath) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (status, limit)).fetchall()
            return [self._row_to_pattern(row) for row in rows]

    def get_pending(self, limit: int = 100) -> List[StoredPattern]:
        return self.get_by_status("proposed", limit=limit)

    def get_accepted(self, limit: int = 100) -> List[StoredPattern]:
        return self.get_by_status("accepted", limit=limit)

    def update_status(self, pattern_id: int, new_status: str) -> tuple[bool, str]:
        if new_status not in self.STATUSES:
            return False, f"Invalid status: {new_status}, use one of {self.STATUSES}"

        if new_status == "proposed":
            return False, "Cannot manually set status to 'proposed', use 'accepted' or 'rejected'"

        with sqlite3.connect(self.dbPath) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT function_name FROM patterns WHERE id = ?", (pattern_id,)
            ).fetchone()
            if not row:
                return False, f"Pattern #{pattern_id} not found."

            conn.execute(
                "UPDATE patterns SET status = ?, reviewed_at = ? WHERE id = ?",
                (new_status, self._now(), pattern_id)
            )
            conn.commit()
            return True, f"Pattern '{row['function_name']}' updated to {new_status}."

    def accept(self, pattern_id: int) -> tuple[bool, str]:
        return self.update_status(pattern_id, "accepted")

    def reject(self, pattern_id: int) -> tuple[bool, str]:
        return self.update_status(pattern_id, "rejected")


    def log_sync(self, root_path: str) -> None:
        sql = "INSERT INTO sync_history (root_path, started_at) VALUES (?, ?)"
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.execute(sql, (str(root_path), self._now()))
            conn.commit()
            return cursor.lastrowid

    def log_sync_complete(
            self,
            sync_id: int,
            functions_found: int,
            patterns_detected: int,
            proposals_generated: int,
    ) -> tuple[bool, str]:
        
        sql = """
        UPDATE sync_history
        SET functions_found = ?,
            patterns_detected = ?,
            proposals_generated = ?,
            completed_at = ?
        WHERE id = ?
        """
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.execute(
                sql,
                (
                    functions_found,
                    patterns_detected,
                    proposals_generated,
                    self._now(),
                    sync_id,
                ),
            )
            conn.commit()
        if cursor.rowcount == 1:
            msg = (
                f"Sync {sync_id} recorded: "
                f"{functions_found} functions, {patterns_detected} patterns, "
                f"{proposals_generated} proposals generated."
            )
            return True, msg
        else:
            msg = f"Warning: Sync ID {sync_id} not found — stats not recorded."
            return False, msg


    def get_recent_syncs(
            self,
            limit: int = 10
    ) -> List[Dict[str, Any]]:
        
        sql = """
            SELECT
                id, root_path, functions_found, patterns_detected,
                proposals_generated, started_at, completed_at
            FROM sync_history
            ORDER BY started_at DESC
            LIMIT ?
        """
        with sqlite3.connect(self.dbPath) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (limit,)).fetchall()
            return [dict(row) for row in rows]


    def get_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'proposed' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
                FROM patterns
                """
            )
            row = cursor.fetchone()
            return {
                "total_patterns": row[0] or 0,
                "pending": row[1] or 0,
                "accepted": row[2] or 0,
                "rejected": row[3] or 0,
            }


    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod 
    def _row_to_pattern(row: sqlite3.Row) -> StoredPattern:
        return StoredPattern(
            id=row["id"],
            function_name=row["function_name"],
            signature=row["signature"],
            implementation=row["implementation"],
            suggested_module=row["suggested_module"],
            description=row["description"],
            confidence_reasoning=row["confidence_reasoning"],
            source_hash=row["source_hash"],
            example_count=row["example_count"],
            status=row["status"],
            created_at=row["created_at"],
            reviewed_at=row["reviewed_at"],
        )