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

        stats = {"accepted": 0, "rejected": 0, "skipped": 0, "reviewed": 0}

        for idx, pattern in enumerate(pending_patterns, 1):
            decision = self._review_single(pattern, idx, len(pending_patterns))

            match decision:
                case "accept":
                    self.store.accept(pattern.id)
                    stats["accepted"] += 1
                    stats["reviewed"] += 1
                case "reject":
                    self.store.reject(pattern.id)
                    stats["rejected"] += 1
                    stats["reviewed"] += 1
                case "skip":
                    stats["skipped"] += 1
                    stats["reviewed"] += 1
                case "quit":
                    break
                 
        remaining = self.store.get_pending(limit=100)
        self._show_summary(stats, len(pending_patterns), remaining)

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
    
    def _show_summary(self, stats: dict, total: int, remaining: List[StoredPattern]) -> None:
            # final stats
            self.console.clear()
            self.console.print("[bold] Review Complete [/bold]\n", justify="center")
    
            table = Table(title="Summary", show_header=True, header_style="bold")
            table.add_column("Decision", style="cyan")
            table.add_column("Count", justify="right", style="magenta")
    
            table.add_row("Accepted", Text(str(stats["accepted"]), style="green"))
            table.add_row("Rejected", Text(str(stats["rejected"]), style="red"))
            table.add_row("Skipped (still pending)", Text(str(stats["skipped"]), style="yellow"))

            never_seen = total - stats["reviewed"] 
            if never_seen > 0:
                table.add_row(
                    "Never reviewed (quit early)",
                    Text(str(never_seen), style="dim red"),
                )

            table.add_row(
                "Total still pending",
                Text(str(len(remaining)), style="bold yellow"),
            )
            self.console.print(table)

            #gist fo whats left
            if remaining:
                self.console.print(f"\n[bold]What's left for review:[/bold]")
                
                rem_table = Table(show_header=True, header_style="dim")
                rem_table.add_column("#", justify="right", style="dim")
                rem_table.add_column("Function", style="green")
                rem_table.add_column("Module", style="yellow")
                rem_table.add_column("Sources", justify="right", style="magenta")
                rem_table.add_column("Preview", style="dim")

                for i, p in enumerate(remaining[:5], 1):
                    # One-line preview: first line of implementation stripped
                    preview = p.implementation.split("\n")[0].strip()[:40]
                    if len(p.implementation.split("\n")[0].strip()) > 40:
                        preview += "…"
                    
                    rem_table.add_row(
                        str(i),
                        p.function_name,
                        p.suggested_module,
                        str(p.example_count),
                        preview,)

            if len(remaining) > 5:
                rem_table.add_row(
                    "",
                    f"… and {len(remaining) - 5} more",
                    "",
                    "",
                    "",
                    style="dim",
                )

            self.console.print(rem_table)

            #what next
            self.console.print()
            if stats["accepted"] > 0:
                self.console.print(
                    f"[green]→[/green] Run [cyan]devdna generate[/cyan] "
                    f"to build SDK with {stats['accepted']} accepted pattern(s)."
                )
            if remaining:
                self.console.print(
                    f"[yellow]→[/yellow] {len(remaining)} pattern(s) still pending. "
                    "Run [cyan]devdna review[/cyan] anytime to continue."
                )
            if not remaining and stats["accepted"] == 0:
                self.console.print(
                    "[dim]All patterns resolved with no acceptances.[/dim]"
                )

