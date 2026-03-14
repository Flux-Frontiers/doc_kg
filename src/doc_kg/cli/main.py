"""
main.py

DocKG CLI entry point.

Usage::

    dockg build       [OPTIONS] [CORPUS_ROOT]
    dockg build-graph [OPTIONS] [CORPUS_ROOT]
    dockg build-index [OPTIONS] [CORPUS_ROOT]
    dockg query       [OPTIONS] QUERY
    dockg pack        [OPTIONS] QUERY
    dockg analyze     [OPTIONS] [CORPUS_ROOT]
    dockg snapshot    [COMMAND]
    dockg viz         [OPTIONS]

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

# Import subcommands so they register against `cli`.
# pylint: disable=unused-import
from doc_kg.cli import (  # noqa: F401
    cmd_analyze,
    cmd_build,
    cmd_hooks,
    cmd_mcp,
    cmd_query,
    cmd_snapshot,
    cmd_viz,
)
from doc_kg.cli.group import cli  # noqa: F401  # pylint: disable=unused-import
