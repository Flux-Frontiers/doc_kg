#!/usr/bin/env python3
"""
dockg.py

DocKG — core primitives and corpus extraction pipeline.

Mirrors the role of codekg.py in CodeKG:
  - Defines the locked graph primitives: DocNode, DocEdge
  - Implements iter_text_files() — the file discovery layer
  - Implements parse_corpus() — the top-level extraction function

Instead of Python AST analysis, parse_corpus() delegates to the TextChunker
(chunker.py) which performs semantically-aware text segmentation.

Node kinds:
  document  — one per .md/.txt file
  section   — a heading-delimited region within a markdown document
  chunk     — a semantically coherent text block within a section

Edge relations:
  CONTAINS   — document→section, section→chunk  (structural hierarchy)
  NEXT       — chunk→chunk  (sequential order within a section)
  REFERENCES — chunk→document  (when a chunk contains a hyperlink to another doc)

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

#: Default sentence-transformer model for general text (not code).
#: Override via the ``DOCKG_MODEL`` environment variable.
DEFAULT_MODEL: str = os.environ.get("DOCKG_MODEL", "all-MiniLM-L6-v2")

# ============================================================================
# Graph primitives (LOCKED v0 CONTRACT)
# ============================================================================


@dataclass(frozen=True)
class DocNode:
    """
    Graph node representing a document, section, or text chunk.

    :param id: Stable node id (e.g. ``doc:notes/journal.md``,
               ``sec:notes/journal.md:introduction``,
               ``chunk:notes/journal.md:0042``)
    :param kind: ``document`` | ``section`` | ``chunk``
    :param name: Short display name (filename stem, section title, or chunk index)
    :param title: Section or document title (None for plain chunks)
    :param file_path: Corpus-relative file path
    :param char_start: Character offset of this node's text in the source file
    :param char_end: End character offset
    :param heading_level: Markdown heading level (1–6) for section nodes; None otherwise
    :param text: Raw text content of this node
    """

    id: str
    kind: str
    name: str
    title: str | None
    file_path: str | None
    char_start: int | None
    char_end: int | None
    heading_level: int | None
    text: str | None


@dataclass(frozen=True)
class DocEdge:
    """
    Graph edge between two DocNodes.

    :param src: Source node id
    :param rel: Relationship type (``CONTAINS``, ``NEXT``, ``REFERENCES``)
    :param dst: Destination node id
    :param evidence: Optional evidence dict (char_start, href, etc.)
    """

    src: str
    rel: str
    dst: str
    evidence: dict | None = None


# ============================================================================
# Constants
# ============================================================================

NODE_KINDS = {"document", "section", "chunk"}
EDGE_KINDS = {"CONTAINS", "NEXT", "REFERENCES", "SIMILAR_TO"}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".dockg",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
}

TEXT_EXTENSIONS = {".md", ".txt", ".rst"}


# ============================================================================
# Node ID helpers
# ============================================================================


def doc_node_id(file_path: str) -> str:
    """Build a stable document node id.

    :param file_path: Corpus-relative file path.
    :return: Node id of the form ``doc:<file_path>``.
    """
    return f"doc:{file_path}"


def section_node_id(file_path: str, section_slug: str) -> str:
    """Build a stable section node id.

    :param file_path: Corpus-relative file path.
    :param section_slug: Slugified section title.
    :return: Node id of the form ``sec:<file_path>:<slug>``.
    """
    return f"sec:{file_path}:{section_slug}"


def chunk_node_id(file_path: str, chunk_index: int) -> str:
    """Build a stable chunk node id.

    :param file_path: Corpus-relative file path.
    :param chunk_index: Zero-based chunk index within the document.
    :return: Node id of the form ``chunk:<file_path>:<index:04d>``.
    """
    return f"chunk:{file_path}:{chunk_index:04d}"


def slugify(text: str) -> str:
    """Convert a heading title to a URL-safe slug.

    :param text: Raw heading text.
    :return: Lowercased, hyphenated slug.
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80]


# ============================================================================
# File discovery
# ============================================================================


def iter_text_files(
    corpus_root: Path,
    extensions: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[Path]:
    """Yield text files under *corpus_root*.

    :param corpus_root: Root directory to search.
    :param extensions: File extensions to include (default: ``.md``, ``.txt``, ``.rst``).
    :param exclude: Extra directory names to skip (combined with ``SKIP_DIRS``).
    :return: Sorted list of matching ``Path`` objects.
    """
    exts = extensions or TEXT_EXTENSIONS
    skip = SKIP_DIRS | (exclude or set())
    found: list[Path] = []
    for root, dirs, files in os.walk(corpus_root):
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith("."))
        for f in sorted(files):
            p = Path(root) / f
            if p.suffix.lower() in exts and not f.startswith("."):
                found.append(p)
    return found


# ============================================================================
# Corpus-relative path helper
# ============================================================================


def rel_file_path(abs_path: Path, corpus_root: Path) -> str:
    """Return the corpus-relative path for *abs_path*, always using forward slashes.

    :param abs_path: Absolute path to a text file.
    :param corpus_root: Root directory of the corpus.
    :return: Relative path string with ``/`` separators.
    """
    try:
        return str(abs_path.relative_to(corpus_root)).replace("\\", "/")
    except ValueError:
        return str(abs_path).replace("\\", "/")


# ============================================================================
# Corpus extraction
# ============================================================================


def parse_corpus(
    corpus_root: Path,
    *,
    extensions: set[str] | None = None,
    exclude: set[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    similarity_threshold: float = 0.75,
    embedder=None,
) -> tuple[list[DocNode], list[DocEdge]]:
    """Extract a document knowledge graph from a corpus directory.

    This function is:
    - Deterministic (same files → same graph, modulo embedding similarity)
    - Side-effect free (no writes)

    For each text file the pipeline is:

    1. Parse structural hierarchy (headings for ``.md``, flat for ``.txt``)
    2. Emit ``document`` and ``section`` nodes + ``CONTAINS`` edges
    3. Semantically chunk the text within each section
    4. Emit ``chunk`` nodes + ``CONTAINS`` and ``NEXT`` edges
    5. Detect hyperlinks and emit ``REFERENCES`` edges

    :param corpus_root: Root directory of the corpus.
    :param extensions: File extensions to include (default: .md, .txt, .rst).
    :param exclude: Extra directory names to skip.
    :param chunk_size: Approximate maximum characters per chunk.
    :param chunk_overlap: Character overlap between consecutive chunks.
    :param similarity_threshold: Cosine-similarity threshold for semantic split detection.
    :param embedder: Optional :class:`~doc_kg.index.Embedder` instance for semantic
                     boundary detection.  When ``None``, structure-only chunking is used.
    :return: ``(nodes, edges)`` tuple.
    """
    from doc_kg.chunker import TextChunker  # local import avoids circular dep

    nodes: dict[str, DocNode] = {}
    edges: dict[tuple[str, str, str], DocEdge] = {}

    chunker = TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        similarity_threshold=similarity_threshold,
        embedder=embedder,
    )

    files = iter_text_files(corpus_root, extensions=extensions, exclude=exclude)

    # Pre-populate all document paths so forward REFERENCES links resolve correctly
    path_to_doc_id: dict[str, str] = {
        rel_file_path(p, corpus_root): doc_node_id(rel_file_path(p, corpus_root))
        for p in files
    }

    for abs_path in files:
        file_path = rel_file_path(abs_path, corpus_root)
        doc_id = doc_node_id(file_path)

        try:
            raw_text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            try:
                raw_text = abs_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

        # Build the document node
        doc_title = _extract_doc_title(raw_text, abs_path)
        nodes[doc_id] = DocNode(
            id=doc_id,
            kind="document",
            name=abs_path.stem,
            title=doc_title,
            file_path=file_path,
            char_start=0,
            char_end=len(raw_text),
            heading_level=None,
            text=raw_text[:512],  # keep first 512 chars as document summary
        )

        # Chunk the document (returns structured chunks with section info)
        chunks = chunker.chunk(raw_text, file_path=file_path)

        # Track the previous chunk id per section for NEXT edges
        prev_chunk_id: str | None = None
        prev_section_slug: str | None = None
        global_chunk_idx = 0
        section_nodes: dict[str, str] = {}  # slug → section_node_id

        for chunk_info in chunks:
            section_title = chunk_info.get("section_title")
            section_level = chunk_info.get("section_level", 1)
            text = chunk_info["text"]
            char_start = chunk_info.get("char_start", 0)
            char_end = chunk_info.get("char_end", len(text))
            references = chunk_info.get("references", [])

            # Create/reuse section node
            if section_title:
                slug = slugify(section_title)
                sec_id = section_node_id(file_path, slug)
                if sec_id not in section_nodes:
                    section_nodes[slug] = sec_id
                    nodes[sec_id] = DocNode(
                        id=sec_id,
                        kind="section",
                        name=section_title,
                        title=section_title,
                        file_path=file_path,
                        char_start=char_start,
                        char_end=char_end,
                        heading_level=section_level,
                        text=None,
                    )
                    # document → section
                    edges[(doc_id, "CONTAINS", sec_id)] = DocEdge(
                        src=doc_id, rel="CONTAINS", dst=sec_id
                    )
                parent_id = sec_id
            else:
                parent_id = doc_id

            # Create chunk node
            chunk_id = chunk_node_id(file_path, global_chunk_idx)
            global_chunk_idx += 1
            nodes[chunk_id] = DocNode(
                id=chunk_id,
                kind="chunk",
                name=f"chunk:{global_chunk_idx:04d}",
                title=section_title,
                file_path=file_path,
                char_start=char_start,
                char_end=char_end,
                heading_level=None,
                text=text,
            )

            # section/document → chunk CONTAINS edge
            edges[(parent_id, "CONTAINS", chunk_id)] = DocEdge(
                src=parent_id, rel="CONTAINS", dst=chunk_id
            )

            # NEXT edge (sequential within same section)
            current_section_slug = slugify(section_title) if section_title else "__root__"
            if prev_chunk_id is not None and prev_section_slug == current_section_slug:
                edges[(prev_chunk_id, "NEXT", chunk_id)] = DocEdge(
                    src=prev_chunk_id, rel="NEXT", dst=chunk_id
                )
            prev_chunk_id = chunk_id
            prev_section_slug = current_section_slug

            # REFERENCES edges (hyperlinks in the chunk text)
            for href in references:
                # Resolve relative links to known documents
                resolved = _resolve_reference(href, file_path, path_to_doc_id)
                if resolved:
                    ref_doc_id = doc_node_id(resolved)
                    edges[(chunk_id, "REFERENCES", ref_doc_id)] = DocEdge(
                        src=chunk_id,
                        rel="REFERENCES",
                        dst=ref_doc_id,
                        evidence={"href": href},
                    )

    return list(nodes.values()), list(edges.values())


# ============================================================================
# Internal helpers
# ============================================================================


def _extract_doc_title(text: str, path: Path) -> str:
    """Extract the document title from the first H1 heading or filename.

    :param text: Raw document text.
    :param path: File path (used as fallback title).
    :return: Title string.
    """
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def _resolve_reference(href: str, source_file: str, path_to_doc_id: dict[str, str]) -> str | None:
    """Attempt to resolve a hyperlink href to a known corpus document path.

    Only resolves relative links (not http/https URLs).

    :param href: Raw href from a link.
    :param source_file: Corpus-relative path of the document containing the link.
    :param path_to_doc_id: Mapping of all known document paths.
    :return: Corpus-relative path of the linked document, or ``None``.
    """
    if href.startswith(("http://", "https://", "ftp://", "#", "mailto:")):
        return None

    # Strip anchor
    href = href.split("#")[0].strip()
    if not href:
        return None

    # Resolve relative to source file's directory
    source_dir = Path(source_file).parent
    try:
        resolved = str((source_dir / href).resolve()).replace("\\", "/")
        # Strip corpus root prefix if we can (not available here, so check by suffix match)
        for known in path_to_doc_id:
            if resolved.endswith(known) or known.endswith(href):
                return known
    except Exception:
        pass

    # Direct match
    if href in path_to_doc_id:
        return href

    return None
