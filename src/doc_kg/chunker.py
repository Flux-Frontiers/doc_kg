#!/usr/bin/env python3
"""
chunker.py

TextChunker — semantic text segmentation for DocKG.

This is the DocKG equivalent of CodeKG's AST visitor (visitor.py).
Instead of walking a syntax tree, it splits natural-language text into
semantically coherent chunks using a two-phase approach:

Phase 1 — Structure parsing (Markdown):
  - Detect ATX headings (# / ## / …) and build a section hierarchy.
  - Each section boundary is a hard split point.

Phase 2 — Semantic chunking within each section (diary-transformer style):
  - Split text into sentences using lightweight regex.
  - If an embedder is provided: embed sentences in batch, compute cosine
    similarities between consecutive sentences, and split when similarity
    drops below *similarity_threshold* (topic boundary detection).
  - If no embedder: fall back to fixed-size character chunking with overlap.
  - Respect a *chunk_size* cap so that no single chunk overwhelms the
    embedding model's context window.

Output is a list of chunk dicts consumed by ``parse_corpus`` in dockg.py:

    {
        "text":           str,       # chunk text
        "section_title":  str|None,  # heading text of the enclosing section
        "section_level":  int|None,  # heading level (1–6), or None
        "char_start":     int,       # byte offset in source file
        "char_end":       int,
        "references":     list[str], # hrefs extracted from this chunk
    }

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doc_kg.index import Embedder


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

# Sentence-ending punctuation followed by whitespace + capital letter or EOL.
# This is intentionally simple — good enough for prose, no NLTK dependency.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\'\(\[])")

# Markdown ATX heading pattern
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Inline hyperlink [text](href)
_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Reference-style link definitions [label]: href
_REF_LINK = re.compile(r"^\[[^\]]+\]:\s+(\S+)", re.MULTILINE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TextChunker:
    """
    Semantic text chunker for Markdown and plain-text documents.

    :param chunk_size: Approximate maximum characters per chunk.
    :param chunk_overlap: Character overlap when a chunk exceeds *chunk_size*
                          and must be split mechanically.
    :param similarity_threshold: Cosine similarity below which a new semantic
                                 chunk is started.  Ignored when no embedder
                                 is provided.
    :param embedder: Optional :class:`~doc_kg.index.Embedder` for semantic
                     boundary detection.
    :param min_chunk_chars: Minimum characters before a chunk is emitted
                            (prevents micro-chunks from headings or empty lines).
    """

    def __init__(
        self,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        similarity_threshold: float = 0.75,
        embedder: Embedder | None = None,
        min_chunk_chars: int = 1,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.similarity_threshold = similarity_threshold
        self.embedder = embedder
        self.min_chunk_chars = min_chunk_chars

    def chunk(self, text: str, *, file_path: str = "") -> list[dict]:
        """Chunk *text* into semantically coherent segments.

        :param text: Raw document text.
        :param file_path: Corpus-relative path (used for plain-text detection).
        :return: List of chunk dicts (see module docstring for schema).
        """
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext in ("md", "markdown"):
            return self._chunk_markdown(text)
        return self._chunk_plain(text)

    # ------------------------------------------------------------------
    # Markdown chunking
    # ------------------------------------------------------------------

    def _chunk_markdown(self, text: str) -> list[dict]:
        """Parse Markdown heading structure and chunk within each section."""
        sections = _split_by_headings(text)
        chunks: list[dict] = []

        for section in sections:
            section_text = section["text"]
            section_title = section["title"]
            section_level = section["level"]
            section_start = section["char_start"]

            if not section_text.strip():
                continue

            sub_chunks = self._semantic_chunks(section_text, base_offset=section_start)

            for sc in sub_chunks:
                refs = _extract_links(sc["text"])
                chunks.append(
                    {
                        "text": sc["text"],
                        "section_title": section_title,
                        "section_level": section_level,
                        "char_start": sc["char_start"],
                        "char_end": sc["char_end"],
                        "references": refs,
                    }
                )

        return chunks

    # ------------------------------------------------------------------
    # Plain text chunking
    # ------------------------------------------------------------------

    def _chunk_plain(self, text: str) -> list[dict]:
        """Chunk plain text (no heading structure)."""
        sub_chunks = self._semantic_chunks(text, base_offset=0)
        result: list[dict] = []
        for sc in sub_chunks:
            refs = _extract_links(sc["text"])
            result.append(
                {
                    "text": sc["text"],
                    "section_title": None,
                    "section_level": None,
                    "char_start": sc["char_start"],
                    "char_end": sc["char_end"],
                    "references": refs,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Core semantic chunking
    # ------------------------------------------------------------------

    def _semantic_chunks(self, text: str, *, base_offset: int = 0) -> list[dict]:
        """Split *text* into semantic chunks.

        Uses embedding-based boundary detection when an embedder is available,
        otherwise falls back to structure-aware fixed-size splitting.

        :param text: Section or document text to split.
        :param base_offset: Character offset of *text* within the source file.
        :return: List of ``{"text", "char_start", "char_end"}`` dicts.
        """
        sentences = _split_sentences(text)
        if not sentences:
            return []

        if self.embedder is not None:
            return self._semantic_boundary_chunks(sentences, text, base_offset)
        return self._fixed_size_chunks(sentences, text, base_offset)

    def _semantic_boundary_chunks(
        self, sentences: list[str], full_text: str, base_offset: int
    ) -> list[dict]:
        """Embedding-based chunking: split at semantic topic boundaries.

        Embeds all sentences, computes consecutive cosine similarities,
        and starts a new chunk when similarity falls below the threshold.
        Also splits mechanically when a chunk exceeds *chunk_size*.
        """
        import numpy as np  # pylint: disable=import-outside-toplevel

        # Batch-embed all sentences
        try:
            vecs = self.embedder.embed_texts(sentences)
        except Exception:
            # Fall back to fixed-size on embedding failure
            return self._fixed_size_chunks(sentences, full_text, base_offset)

        # Compute cosine similarities between consecutive sentence vectors
        sims: list[float] = []
        for i in range(len(vecs) - 1):
            a = np.asarray(vecs[i], dtype="float32")
            b = np.asarray(vecs[i + 1], dtype="float32")
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na > 0 and nb > 0:
                sims.append(float(np.dot(a, b) / (na * nb)))
            else:
                sims.append(1.0)

        # Group sentences into chunks at boundary points
        groups: list[list[str]] = [[sentences[0]]]
        for i, sim in enumerate(sims):
            next_sent = sentences[i + 1]
            current_text = " ".join(groups[-1])

            # Start a new chunk if: semantic boundary OR size exceeded
            if (
                sim < self.similarity_threshold
                or len(current_text) + len(next_sent) > self.chunk_size
            ):
                groups.append([next_sent])
            else:
                groups[-1].append(next_sent)

        return _groups_to_chunks(groups, full_text, base_offset, self.min_chunk_chars)

    def _fixed_size_chunks(
        self, sentences: list[str], full_text: str, base_offset: int
    ) -> list[dict]:
        """Structure-aware fixed-size chunking (no embedder required).

        Groups sentences until *chunk_size* is reached, then starts a new chunk
        with *chunk_overlap* characters of lookahead.
        """
        groups: list[list[str]] = [[]]
        for sent in sentences:
            current = " ".join(groups[-1])
            if groups[-1] and len(current) + len(sent) > self.chunk_size:
                # Overlap: carry last sentence(s) into the new chunk
                overlap_sents: list[str] = []
                carried = 0
                for prev in reversed(groups[-1]):
                    if carried + len(prev) > self.chunk_overlap:
                        break
                    overlap_sents.insert(0, prev)
                    carried += len(prev)
                groups.append(overlap_sents + [sent])
            else:
                groups[-1].append(sent)

        return _groups_to_chunks(groups, full_text, base_offset, self.min_chunk_chars)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_by_headings(text: str) -> list[dict]:
    """Split Markdown text into sections delimited by ATX headings.

    Returns a list of section dicts:
    ``{"title": str|None, "level": int|None, "text": str, "char_start": int}``

    The preamble before the first heading becomes a section with ``title=None``.

    :param text: Raw Markdown document text.
    :return: List of section dicts.
    """
    sections: list[dict] = []
    last_pos = 0
    last_title: str | None = None
    last_level: int | None = None

    for m in _HEADING.finditer(text):
        # Emit the text up to this heading as the previous section's body
        prev_text = text[last_pos : m.start()]
        if prev_text.strip() or last_title is not None:
            sections.append(
                {
                    "title": last_title,
                    "level": last_level,
                    "text": prev_text,
                    "char_start": last_pos,
                }
            )
        last_title = m.group(2).strip()
        last_level = len(m.group(1))
        last_pos = m.end()

    # Remaining text after the last heading
    tail = text[last_pos:]
    if tail.strip() or last_title is not None:
        sections.append(
            {
                "title": last_title,
                "level": last_level,
                "text": tail,
                "char_start": last_pos,
            }
        )

    # If no headings at all, treat entire doc as one section
    if not sections:
        sections.append({"title": None, "level": None, "text": text, "char_start": 0})

    return sections


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences using lightweight regex.

    Falls back to paragraph splitting when sentence splitting yields too few
    sentences (good for bullet lists and tables).

    :param text: Input text.
    :return: Non-empty sentence strings.
    """
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    if len(sents) <= 1:
        # Try paragraph splitting as fallback
        sents = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not sents:
        sents = [text.strip()] if text.strip() else []
    return sents


def _groups_to_chunks(
    groups: list[list[str]],
    full_text: str,
    base_offset: int,
    min_chunk_chars: int,
) -> list[dict]:
    """Convert sentence groups into chunk dicts with character offsets.

    :param groups: List of sentence lists.
    :param full_text: Original section text (used to locate char offsets).
    :param base_offset: Character offset of *full_text* in the source file.
    :param min_chunk_chars: Drop chunks shorter than this.
    :return: List of ``{"text", "char_start", "char_end"}`` dicts.
    """
    chunks: list[dict] = []
    search_from = 0

    for group in groups:
        if not group:
            continue
        chunk_text = " ".join(group)
        if len(chunk_text) < min_chunk_chars:
            continue

        # Locate the chunk in the full section text
        first_sent = group[0]
        pos = full_text.find(first_sent, search_from)
        if pos == -1:
            pos = search_from

        last_sent = group[-1]
        end_pos = full_text.find(last_sent, pos)
        if end_pos == -1:
            end_pos = pos + len(chunk_text)
        else:
            end_pos += len(last_sent)

        chunks.append(
            {
                "text": chunk_text,
                "char_start": base_offset + pos,
                "char_end": base_offset + end_pos,
            }
        )
        search_from = pos

    return chunks


def _extract_links(text: str) -> list[str]:
    """Extract all hyperlink hrefs from Markdown text.

    :param text: Chunk text (Markdown).
    :return: List of raw href strings.
    """
    hrefs: list[str] = []
    for m in _LINK.finditer(text):
        hrefs.append(m.group(2).strip())
    for m in _REF_LINK.finditer(text):
        hrefs.append(m.group(1).strip())
    return hrefs
