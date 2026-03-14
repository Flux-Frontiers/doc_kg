"""
group.py

Defines the root Click group for the DocKG CLI.
Kept in a separate module so cmd_* submodules can import `cli` without
creating a cyclic dependency with main.py.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import click


@click.group()
@click.version_option(package_name="doc-kg", prog_name="dockg")
def cli() -> None:
    """DocKG - Document Knowledge Graph builder and query tool.

    Builds a semantically searchable knowledge graph from .md and .txt files.
    """
