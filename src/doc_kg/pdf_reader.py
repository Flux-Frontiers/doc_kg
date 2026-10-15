"""
pdf_reader.py

PDF text extraction for DocKG, delegated to the fleet's one PDF converter,
:class:`kg_utils.ingest.PdfConverter` (sweep item 48).

The converter makes the same bare ``pymupdf4llm.to_markdown()`` call this
module used to make, so the Markdown is byte-identical: headings inferred
from font size and style still flow into the existing ``_chunk_markdown()``
path in chunker.py, and ``kgrag ingest`` and ``dockg build`` convert a PDF
the same way.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

from kg_utils.ingest import PdfConverter


def extract_pdf_markdown(path: Path) -> str:
    """Extract text from a PDF as Markdown using pymupdf4llm.

    Headings are inferred from font size/weight and written as ATX headings
    (``# Title``, ``## Section``, …), so the output is consumed by
    :meth:`~doc_kg.chunker.TextChunker._chunk_markdown` exactly like a
    hand-written ``.md`` file.

    :param path: Absolute path to the PDF file.
    :return: Markdown-formatted document text.
    :raises RuntimeError: If the file cannot be opened or parsed, or has no
        text layer (a scanned PDF needing OCR). The error is a
        :class:`kg_utils.ingest.ConversionError`, a ``RuntimeError`` subclass,
        whose message says which.
    """
    return PdfConverter().convert(Path(path)).markdown
