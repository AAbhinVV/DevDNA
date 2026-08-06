# Typer commands tying all DevDNA components together

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from devdna.core.analyzer import analyze_patterns
from devdna.core.generator import SDKGenerator
from devdna.core.llm_bridge import LLMBridge
from devdna.core.memory import MemoryStore
from devdna.core.scanner import scan_directory
from devdna.ui.review import ReviewUI

app = typer.Typer(
    name = "DevDNA",
    help = "DevDNA — Turn your muscle memory into a reusable SDK.",
    no_args_is_help = True,
)

console = Console()

@app.command()
def sync(
    path: Path = typer.Argument(
        Path("."),
        help="Directory to scan for Python files.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        ),
        min_cluster_size: int = typer.Option(
            2,
            "--min-cluster",
            "-m",
            help="Minimum occurrences to form a pattern cluster.",
        ),
        max_clusters: int = typer.Option(
            50,
            "--max-clusters",
            "-n",
            help="Maximum patterns to send to LLM.",
        ),
    ) -> None:
    """
    Scan a codebase, detect patterns, and generate proposals via LLM.
    """
    store = MemoryStore()
    sync_id = store.log_sync_start(path)

    console.print(f"[bold cyan]Scanning[/bold cyan] {path} ...")
    blocks = scan_directory(path)
    console.print(f"  Found {len(blocks)} function(s)")

    if not blocks:
        console.print("[yellow]No functions found. Nothing to do.[/yellow]")
        store.log_sync_complete(sync_id, 0, 0, 0)
        return

    console.print("[bold cyan]Analyzing[/bold cyan] patterns ...")
    clusters = analyze_patterns(blocks, min_cluster_size, max_clusters)
    console.print(f"  Detected {len(clusters)} pattern cluster(s)")

    if not clusters:
        console.print("[yellow]No patterns detected. Try lowering --min-cluster.[/yellow]")
        store.log_sync_complete(sync_id, len(blocks), 0, 0)
        return

    console.print("[bold cyan]Generating[/bold cyan] proposals via LLM ...")
    bridge = LLMBridge()
    proposals = bridge.propose_batch(clusters)

    saved = 0
    for proposal in proposals:
        pid = store.save_proposal(
            {
                "function_name": proposal.function_name,
                "signature": proposal.signature,
                "implementation": proposal.implementation,
                "suggested_module": proposal.suggested_module,
                "description": proposal.description,
                "confidence_reasoning": proposal.confidence_reasoning,
                "source_hash": proposal.source_hash,
                "example_count": proposal.example_count,
            }
        )
        if pid:
            saved += 1

        ok, msg = store.log_sync_complete(sync_id, len(blocks), len(clusters), saved)
        console.print(f"[green]{msg}[/green]" if ok else f"[yellow]{msg}[/yellow]")

        console.print(
            f"\n[bold]Next step:[/bold] Run [cyan]devdna review[/cyan] to inspect {saved} proposal(s)."
        )


@app.command()
def review() -> None:
    ui = ReviewUI()
    ui.run()

@app.command()
def generate(
    package_name: str = typer.Option(
        "devdna_sdk",
        "--name",
        "-n",
        help="Name of the generated Python package.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Directory to write the SDK. Defaults to ~/.devdna/sdk",
    ),
    version: str = typer.Option(
        "0.1.0",
        "--version",
        "-v",
        help="SDK version string.",
    ),
) -> None:
    """
    Generate a pip-installable SDK from accepted patterns.
    """
    store = MemoryStore()
    accepted = store.get_accepted(limit=1000)

    if not accepted:
        console.print(
            "[yellow]No accepted patterns. Run `devdna review` first.[/yellow]"
        )
        raise typer.Exit(1)

    gen = SDKGenerator(
        package_name=package_name,
        output_dir=output_dir,
        version=version,
    )
    path = gen.generate(accepted)

    console.print(f"[bold green]SDK generated at[/bold green] {path}")
    console.print(f"[dim]Install:[/dim] [cyan]pip install -e {path}[/cyan]")
