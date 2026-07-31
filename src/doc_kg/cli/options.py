"""
options.py

Shared Click options for DocKG CLI commands.
"""

from __future__ import annotations

import click

from doc_kg.dockg import DEFAULT_MODEL

sqlite_option = click.option(
    "--sqlite",
    default=None,
    show_default=False,
    type=click.Path(),
    help="Path to SQLite database (default: <repo>/.dockg/graph.sqlite).",
)

lancedb_option = click.option(
    "--lancedb",
    default=None,
    show_default=False,
    type=click.Path(),
    help="Path to LanceDB directory (default: <repo>/.dockg/lancedb).",
)

vectors_path_option = click.option(
    "--vectors-path",
    default=None,
    show_default=False,
    type=click.Path(),
    help="Path to the sqlite-vec vector store (default: <repo>/.dockg/vectors.sqlite, "
    "derived next to the graph). Set this when the store lives elsewhere; an "
    "explicit path also lets --vector-backend=auto resolve to sqlite-vec.",
)

vector_backend_option = click.option(
    "--vector-backend",
    default=None,
    show_default=False,
    type=click.Choice(["auto", "lancedb", "sqlite-vec"]),
    help="Vector store backend (default: sqlite-vec, or $DOCKG_VECTOR_BACKEND). "
    "sqlite-vec is exact and ~10x smaller (<repo>/.dockg/vectors.sqlite). "
    "auto and lancedb read a pre-0.20.0 store and need the [lancedb] extra: "
    "pip install 'doc-kg[lancedb]'.",
)

model_option = click.option(
    "--model",
    default=DEFAULT_MODEL,
    show_default=True,
    help="Sentence-transformer model name.",
)

corpus_root_option = click.option(
    "--corpus-root",
    default=".",
    type=click.Path(exists=True, file_okay=False),
    show_default=True,
    help="Root directory of the document corpus.",
)

repo_option = click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True, file_okay=False),
    show_default=True,
    help="Root directory of the document corpus.",
)
