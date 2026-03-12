"""
config.py — Configuration utilities for DocKG.

Reads and parses DocKG configuration from pyproject.toml.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def load_exclude_dirs(corpus_root: Path | str) -> set[str]:
    """Load exclude directory names from ``[tool.dockg].exclude`` in pyproject.toml.

    Excluded directory names are pruned at every level during the file walk,
    combined with the built-in ``SKIP_DIRS`` constant in ``dockg.py``.

    Example::

        # pyproject.toml
        [tool.dockg]
        exclude = [".dockg", ".codekg", "src", "node_modules"]

    :param corpus_root: Corpus root directory (where pyproject.toml lives).
    :return: Set of directory names to exclude.
             An empty set means no extra exclusions beyond ``SKIP_DIRS``.
    """
    corpus_root = Path(corpus_root)
    pyproject_path = corpus_root / "pyproject.toml"

    if not pyproject_path.exists():
        return set()

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return set()

    value = data.get("tool", {}).get("dockg", {}).get("exclude", [])
    if isinstance(value, list):
        return {d.rstrip("/") for d in value if isinstance(d, str)}
    return set()
