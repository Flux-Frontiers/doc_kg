"""
cmd_analyze.py

Click subcommand for running a thorough DocKG corpus analysis:

  analyze  — run DocKGAnalyzer, emit a Markdown report and JSON snapshot
"""

from __future__ import annotations

import click

from doc_kg.cli.group import cli
from doc_kg.cli.options import repo_option
from doc_kg.dockg_thorough_analysis import main as run_analysis


@cli.command("analyze")
@repo_option
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="SQLite knowledge graph path (default: <corpus>/.dockg/graph.sqlite).",
)
@click.option(
    "--lancedb",
    default=None,
    type=click.Path(),
    help="LanceDB vector index directory (default: <corpus>/.dockg/lancedb).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Markdown report output path (default: <corpus>/analysis/doc_kg_analysis_<YYYYMMDD>.md).",
)
@click.option(
    "--json",
    "-j",
    "json_path",
    default=None,
    type=click.Path(),
    help="JSON snapshot output path (default: ~/.claude/dockg_analysis_latest.json).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress the Rich console summary table.",
)
def analyze(
    repo: str,
    db: str | None,
    lancedb: str | None,
    output: str | None,
    json_path: str | None,
    quiet: bool,
) -> None:
    """Run a thorough analysis of a document corpus graph."""
    run_analysis(
        corpus_root=repo,
        db_path=db,
        lancedb_path=lancedb,
        report_path=output,
        json_path=json_path,
        quiet=quiet,
    )
