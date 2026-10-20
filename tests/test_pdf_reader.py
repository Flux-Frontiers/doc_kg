"""Tests for PDF ingestion: pdf_reader, iter_text_files, chunker dispatch, parse_corpus."""

import pymupdf
import pytest

from doc_kg.chunker import TextChunker
from doc_kg.dockg import TEXT_EXTENSIONS, iter_text_files, parse_corpus
from doc_kg.pdf_reader import extract_pdf_markdown

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_pdf(tmp_path):
    """Write a minimal two-section PDF using PyMuPDF and return its path."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Introduction", fontsize=18)
    page.insert_text((50, 120), "This is the introduction section with some content.")
    page.insert_text((50, 180), "Background", fontsize=18)
    page.insert_text((50, 228), "This is the background section with more content.")
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def pdf_corpus(simple_pdf, tmp_path):
    """A corpus directory that contains one PDF alongside one Markdown file."""
    (tmp_path / "readme.md").write_text("# Overview\n\nSome overview text.\n")
    return tmp_path


# ---------------------------------------------------------------------------
# pdf_reader
# ---------------------------------------------------------------------------


def test_extract_pdf_markdown_returns_string(simple_pdf):
    md = extract_pdf_markdown(simple_pdf)
    assert isinstance(md, str)
    assert len(md) > 0


def test_extract_pdf_markdown_contains_headings(simple_pdf):
    md = extract_pdf_markdown(simple_pdf)
    assert "Introduction" in md
    assert "Background" in md


def test_extract_pdf_markdown_raises_on_corrupt_file(tmp_path):
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(RuntimeError):
        extract_pdf_markdown(bad)


# ---------------------------------------------------------------------------
# TEXT_EXTENSIONS and iter_text_files
# ---------------------------------------------------------------------------


def test_pdf_in_text_extensions():
    assert ".pdf" in TEXT_EXTENSIONS


def test_iter_text_files_discovers_pdf(pdf_corpus):
    found = {p.name for p in iter_text_files(pdf_corpus)}
    assert "sample.pdf" in found
    assert "readme.md" in found


# ---------------------------------------------------------------------------
# Chunker dispatch
# ---------------------------------------------------------------------------


def test_chunker_routes_pdf_through_markdown(simple_pdf):
    md = extract_pdf_markdown(simple_pdf)
    chunker = TextChunker()
    chunks = chunker.chunk(md, file_path="docs/sample.pdf")
    assert len(chunks) >= 1
    # All chunks should carry section titles (markdown path, not plain path)
    titled = [c for c in chunks if c["section_title"] is not None]
    assert len(titled) > 0


# ---------------------------------------------------------------------------
# parse_corpus end-to-end
# ---------------------------------------------------------------------------


def test_parse_corpus_includes_pdf_document_node(pdf_corpus):
    nodes, _ = parse_corpus(pdf_corpus, quiet=True)
    doc_ids = {n.id for n in nodes if n.kind == "document"}
    assert any("sample.pdf" in did for did in doc_ids)


def test_parse_corpus_pdf_produces_chunks(pdf_corpus):
    nodes, edges = parse_corpus(pdf_corpus, quiet=True)
    chunk_nodes = [n for n in nodes if n.kind == "chunk" and "sample.pdf" in (n.file_path or "")]
    assert len(chunk_nodes) >= 1


def test_parse_corpus_pdf_sections_from_headings(pdf_corpus):
    nodes, _ = parse_corpus(pdf_corpus, quiet=True)
    section_nodes = [
        n for n in nodes if n.kind == "section" and "sample.pdf" in (n.file_path or "")
    ]
    titles = {n.title for n in section_nodes}
    assert "Introduction" in titles or "Background" in titles


# ---------------------------------------------------------------------------
# Delegation to kg_utils.ingest.PdfConverter (sweep item 48)
# ---------------------------------------------------------------------------


def test_extract_pdf_markdown_matches_the_direct_pymupdf4llm_call(simple_pdf):
    """Delegating to the SDK converter must not change a byte of output."""
    import pymupdf4llm

    assert extract_pdf_markdown(simple_pdf) == pymupdf4llm.to_markdown(str(simple_pdf))


def test_scanned_pdf_raises_and_is_skipped_not_empty(tmp_path):
    """A PDF with no text layer is skipped by parse_corpus, never an empty node."""
    doc = pymupdf.open()
    doc.new_page()  # no text: what a scan looks like to pymupdf4llm
    scanned = tmp_path / "scan.pdf"
    doc.save(str(scanned))
    doc.close()
    (tmp_path / "readme.md").write_text("# Overview\n\nSome overview text.\n")

    with pytest.raises(RuntimeError, match="OCR"):
        extract_pdf_markdown(scanned)
    nodes, _ = parse_corpus(tmp_path, quiet=True)
    assert not [n for n in nodes if n.kind == "document" and "scan.pdf" in (n.file_path or "")]
    assert [n for n in nodes if n.kind == "document" and "readme.md" in (n.file_path or "")]
