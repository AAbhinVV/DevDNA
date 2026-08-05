from __future__ import annotations

from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from devdna.core.memory import MemoryStore, StoredPattern

class ReviewUI:
    def __init__(self, store: Optional[MemoryStore] = None) -> None:
        self.console = Console()
        self.store = store or MemoryStore()

    def run(self) -> None:
        # main entry point, fetches patterns adn runs review loop
        pending_patterns = self.store.get_pending(limit=100)

        if not pending_patterns:
            self.console.print("[bold green]✓[/bold green] No pending proposals. "
                "Run [cyan]devdna sync[/cyan] to discover new patterns.")
            return

        self.console.print(
            f"[bold]Found {len(pending_patterns)} proposal(s) to review.[/bold]\n"
        )

        stats = {"accepted": 0, "rejected": 0, "skipped": 0}

        for idx, pattern in enumerate(pending_patterns, 1):
            decision = self._review_single(pattern, idx, len(pending_patterns))

            match decision:
                case "accept":
                    self.store.accept(pattern.id)
                    stats["accepted"] += 1
                case "reject":
                    self.store.reject(pattern.id)
                    stats["rejected"] += 1
                case "skip":
                    stats["skipped"] += 1
                case "quit":
                    break

        self._show_summary(stats, len(pending_patterns))

    