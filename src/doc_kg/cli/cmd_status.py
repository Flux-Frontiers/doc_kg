"""
cmd_status.py

Click subcommand for displaying live DocKG graph status:

  status  — show node/edge counts, builder metadata, and DB file size

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from doc_kg.cli.group import cli
from doc_kg.cli.options import repo_option, sqlite_option
from doc_kg.store import GraphStore

_console = Console()


def _read_kgrag_meta(db_path: Path) -> dict[str, str]:
    """Read all rows from ``_kgrag_meta`` without opening a GraphStore."""
    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False)
        rows = con.execute("SELECT key, value FROM _kgrag_meta").fetchall()
        con.close()
        return {k: v for k, v in rows}
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return {}


@cli.command("status")
@repo_option
@sqlite_option
def status(repo: str, sqlite: str) -> None:
    """Show live node/edge counts and builder metadata for the graph store."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"

    if not db_path.exists():
        _console.print(f"[red]Graph store not found:[/red] {db_path}")
        raise SystemExit(1)

    db_size_mb = round(db_path.stat().st_size / 1_048_576, 2)
    meta = _read_kgrag_meta(db_path)

    store = GraphStore(db_path)
    s = store.stats()
    store.close()

    nc = s.get("node_counts", {})
    ec = s.get("edge_counts", {})
    total_nodes = s.get("total_nodes", 0)
    total_edges = s.get("total_edges", 0)

    builder_name = meta.get("builder_name", "?")
    builder_ver = meta.get("builder_version", "?")
    built_at = meta.get("built_at", "?")

    _console.print(Rule(f"DocKG Status — {db_path}", style="bold blue"))
    _console.print(f"  Builder  : {builder_name} {builder_ver}")
    _console.print(f"  Built at : {built_at}")
    _console.print(f"  DB size  : {db_size_mb} MB")
    _console.print()

    # Node counts table
    node_table = Table(title="Nodes", show_header=True, header_style="bold")
    node_table.add_column("Kind", style="cyan")
    node_table.add_column("Count", justify="right")

    for kind in ("document", "chunk", "section", "topic", "entity", "keyword"):
        count = nc.get(kind, 0)
        if count:
            node_table.add_row(kind, f"{count:,}")

    for kind, count in sorted(nc.items()):
        if kind not in {"document", "chunk", "section", "topic", "entity", "keyword"}:
            node_table.add_row(kind, f"{count:,}")

    node_table.add_section()
    node_table.add_row("[bold]total[/bold]", f"[bold]{total_nodes:,}[/bold]")

    # Edge counts table
    edge_table = Table(title="Edges", show_header=True, header_style="bold")
    edge_table.add_column("Relation", style="cyan")
    edge_table.add_column("Count", justify="right")

    for rel, count in sorted(ec.items(), key=lambda x: -x[1]):
        edge_table.add_row(rel, f"{count:,}")

    edge_table.add_section()
    edge_table.add_row("[bold]total[/bold]", f"[bold]{total_edges:,}[/bold]")

    from rich.columns import Columns  # pylint: disable=import-outside-toplevel

    _console.print(Columns([node_table, edge_table]))
