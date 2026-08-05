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

    def _review_single(self, pattern: StoredPattern, current: int, total: int) -> str:
            # Implementation for reviewing a single pattern
            self.console.clear()
    
            header = Text.assemble(
                 ("DevDNA Review", "bold cyan"),
                " — ",
                (f"Pattern {current} of {total}", "dim"),
            )
            self.console.print(header, justify = "center")
            self.console.rule()
    
            metadata = Text.assemble(
                ("Name: ", "bold"), (pattern.function_name, "green"), "\n",
                ("Module: ", "bold"), (pattern.suggested_module, "yellow"), "\n",
                ("Sources: ", "bold"), (str(pattern.example_count), "magenta"), " files\n",
                ("Hash: ", "bold"), (pattern.source_hash[:8] + "...", "dim"),
            )
            self.console.print(Panel(metadata, title="Metadata", border_style="blue"))
    
            code_syntax = Syntax(
                pattern.implementation,
                "python",
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
    
            self.console.print(Panel(code_syntax, title="Proposed Implementation", border_style="green"))
    
            # confidence reasoning
            if pattern.confidence_reasoning:
                self.console.print(Panel(pattern.confidence_reasoning, title="Confidence Reasoning", border_style="yellow",))
    
            # decision prompt
            self.console.print()
            choice = Prompt.ask(
                "[bold]Decision[/bold]",
                choices=["a", "r", "s", "q"],
                show_choices=True,
                case_sensitive=False,
            )
    
            return {
                "a": "accept",
                "r": "reject",
                "s": "skip",
                "q": "quit",
            }[choice.lower()]
    
    def _show_summary(self, stats: dict, total: int) -> None:
            # final stats
            self.console.clear()
            self.console.print("[bold] Review Complete [/bold]\n", justify="center")
    
            table = Table(title="Summary", show_header=True, header_style="bold")
            table.add_column("Decision", style="cyan")
            table.add_column("Count", justify="right", style="magenta")
    
            table.add_row("Accepted", str(stats["accepted"]))
            table.add_row("Rejected", str(stats["rejected"]))
            table.add_row("Skipped (remain pending)", str(stats["skipped"]))
            table.add_row("Remaining unreviewed", str(
                total - stats["accepted"] - stats["rejected"] - stats["skipped"]
            ), style="dim")
        