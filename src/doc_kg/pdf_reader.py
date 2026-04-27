"""
pdf_reader.py

PDF text extraction for DocKG via pymupdf4llm.

Converts PDF pages to Markdown, preserving heading structure inferred from
font size and style so the result flows naturally into the existing
_chunk_markdown() path in chunker.py.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import pymupdf4llm


def extract_pdf_markdown(path: Path) -> str:
    """Extract text from a PDF as Markdown using pymupdf4llm.

    Headings are inferred from font size/weight and written as ATX headings
    (``# Title``, ``## Section``, …), so the output is consumed by
    :meth:`~doc_kg.chunker.TextChunker._chunk_markdown` exactly like a
    hand-written ``.md`` file.

    :param path: Absolute path to the PDF file.
    :return: Markdown-formatted document text.
    :raises RuntimeError: If pymupdf4llm cannot open or parse the file.
    """
    try:
        return pymupdf4llm.to_markdown(str(path))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pymupdf4llm could not parse {path}: {exc}") from exc
