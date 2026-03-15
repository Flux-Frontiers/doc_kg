"""
cmd_semantic_analyze.py

Click subcommand for semantic DocKG corpus analysis:

  semantic-analyze  — topics, themes, entities, language measures, document signatures
"""

from __future__ import annotations

import click

from doc_kg.cli.group import cli
from doc_kg.cli.options import repo_option
from doc_kg.dockg_semantic_analysis import main as run_semantic_analysis


@cli.command("semantic-analyze")
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
    help="Markdown report output path (default: <corpus>/analysis/doc_kg_semantic_<YYYYMMDD>.md).",
)
@click.option(
    "--json",
    "-j",
    "json_path",
    default=None,
    type=click.Path(),
    help="JSON output path (default: ~/.claude/dockg_semantic_latest.json).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress the Rich console summary table.",
)
def semantic_analyze(
    repo: str,
    db: str | None,
    lancedb: str | None,
    output: str | None,
    json_path: str | None,
    quiet: bool,
) -> None:
    """Semantic analysis: topics, themes, entities, language measures, document signatures."""
    run_semantic_analysis(
        corpus_root=repo,
        db_path=db,
        lancedb_path=lancedb,
        report_path=output,
        json_path=json_path,
        quiet=quiet,
    )
