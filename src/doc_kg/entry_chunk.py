#!/usr/bin/env python3
"""
entry_chunk.py

Structured per-chunk result with full source provenance and topic metadata.

This is Phase 4 of the multipass analysis pipeline — the intermediate
representation produced after diversity sampling, chunking, and topic
classification have run.  Each ``EntryChunk`` records:

- the chunk text
- where it came from (file, char offsets, section)
- how it was classified (topic, confidence, method)
- an optional embedding vector

``EntryChunk`` is deliberately decoupled from the graph layer (``DocNode`` /
``DocEdge``).  A convenience ``to_node_dict()`` method returns a dict
compatible with ``GraphStore.write()`` so results *can* be persisted, but the
dataclass itself has no dependency on ``store.py`` or ``dockg.py``.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SourceProvenance:
    """Tracks exactly where a chunk came from in the source corpus.

    :param file_path: Corpus-relative file path.
    :param char_start: Start character offset in the source file.
    :param char_end: End character offset in the source file.
    :param section_title: Enclosing Markdown section title, if any.
    :param section_level: Heading level (1-6), or ``None``.
    :param chunk_index: Zero-based position of this chunk within its document.
    """

    file_path: str
    char_start: int
    char_end: int
    section_title: str | None = None
    section_level: int | None = None
    chunk_index: int = 0


@dataclass
class EntryChunk:
    """A single processed chunk from the multipass analysis pipeline.

    Produced by Phase 4 (Memory Creation) after sampling, chunking, and
    classification have run.

    :param chunk_id: Stable hash-based identifier.
    :param text: Chunk text content.
    :param provenance: Where this chunk came from.
    :param topics: List of ``(topic_name, score)`` tuples from classification.
    :param topic_method: Which classifier produced the winning topic.
    :param topic_confidence: Confidence of the top topic assignment.
    :param keywords: Extracted keywords for this chunk.
    :param entities: Extracted entities for this chunk.
    :param embedding: Optional float32 embedding vector.
    :param run_id: Pipeline run identifier (links chunks to a specific run).
    """

    chunk_id: str
    text: str
    provenance: SourceProvenance
    topics: list[tuple[str, float]] = field(default_factory=list)
    topic_method: Literal["supervised", "unsupervised", "fallback"] = "supervised"
    topic_confidence: float = 0.0
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    run_id: str = ""

    @property
    def primary_topic(self) -> str:
        """Return the highest-scoring topic name, or ``'unclassified'``."""
        if self.topics:
            return self.topics[0][0]
        return "unclassified"

    def to_node_dict(self) -> dict:
        """Return a dict compatible with ``GraphStore`` node schema.

        This bridges the pipeline output back to the graph layer without
        importing ``DocNode``.
        """
        return {
            "id": self.chunk_id,
            "kind": "chunk",
            "name": f"pipeline:{self.provenance.chunk_index:04d}",
            "title": self.provenance.section_title,
            "file_path": self.provenance.file_path,
            "char_start": self.provenance.char_start,
            "char_end": self.provenance.char_end,
            "heading_level": self.provenance.section_level,
            "text": self.text,
        }


def make_chunk_id(file_path: str, char_start: int, text: str) -> str:
    """Build a stable, content-addressed chunk ID.

    :param file_path: Corpus-relative path.
    :param char_start: Start offset.
    :param text: Chunk text (first 256 chars used for hash).
    :return: ID of the form ``pchunk:<file>:<hash8>``.
    """
    payload = f"{file_path}:{char_start}:{text[:256]}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"pchunk:{file_path}:{digest}"
