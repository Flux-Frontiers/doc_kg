"""Tests for entry_chunk.py — SourceProvenance, EntryChunk, make_chunk_id."""

import dataclasses
import hashlib

from doc_kg.entry_chunk import EntryChunk, SourceProvenance, make_chunk_id


# ---------------------------------------------------------------------------
# SourceProvenance
# ---------------------------------------------------------------------------


def test_source_provenance_creation():
    prov = SourceProvenance(file_path="docs/intro.md", char_start=0, char_end=100)
    assert prov.file_path == "docs/intro.md"
    assert prov.char_start == 0
    assert prov.char_end == 100
    assert prov.section_title is None
    assert prov.section_level is None
    assert prov.chunk_index == 0


def test_source_provenance_with_optional_fields():
    prov = SourceProvenance(
        file_path="notes.md",
        char_start=50,
        char_end=200,
        section_title="Introduction",
        section_level=1,
        chunk_index=3,
    )
    assert prov.section_title == "Introduction"
    assert prov.section_level == 1
    assert prov.chunk_index == 3


def test_source_provenance_is_frozen():
    prov = SourceProvenance(file_path="a.md", char_start=0, char_end=10)
    assert dataclasses.is_dataclass(prov)
    # Frozen dataclass raises FrozenInstanceError on mutation
    try:
        prov.char_start = 999  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except (dataclasses.FrozenInstanceError, TypeError, AttributeError):
        pass  # expected


def test_source_provenance_equality():
    prov1 = SourceProvenance(file_path="a.md", char_start=0, char_end=10)
    prov2 = SourceProvenance(file_path="a.md", char_start=0, char_end=10)
    assert prov1 == prov2


def test_source_provenance_hashable():
    prov = SourceProvenance(file_path="a.md", char_start=0, char_end=10)
    # Frozen dataclasses are hashable
    s = {prov}
    assert prov in s


# ---------------------------------------------------------------------------
# EntryChunk
# ---------------------------------------------------------------------------


def _make_provenance(**kwargs) -> SourceProvenance:
    defaults = {"file_path": "test.md", "char_start": 0, "char_end": 50}
    defaults.update(kwargs)
    return SourceProvenance(**defaults)


def test_entry_chunk_creation_with_defaults():
    prov = _make_provenance()
    chunk = EntryChunk(
        chunk_id="pchunk:test.md:abc12345",
        text="Hello world.",
        provenance=prov,
    )
    assert chunk.chunk_id == "pchunk:test.md:abc12345"
    assert chunk.text == "Hello world."
    assert chunk.provenance is prov
    assert chunk.topics == []
    assert chunk.topic_method == "supervised"
    assert chunk.topic_confidence == 0.0
    assert chunk.keywords == []
    assert chunk.entities == []
    assert chunk.embedding is None
    assert chunk.run_id == ""


def test_entry_chunk_creation_with_all_fields():
    prov = _make_provenance(section_title="Background", section_level=2, chunk_index=1)
    chunk = EntryChunk(
        chunk_id="pchunk:test.md:deadbeef",
        text="Architecture discussion.",
        provenance=prov,
        topics=[("architecture", 0.85), ("design", 0.6)],
        topic_method="supervised",
        topic_confidence=0.85,
        keywords=["architecture", "design"],
        entities=["DocKG"],
        embedding=[0.1, 0.2, 0.3],
        run_id="run-abc",
    )
    assert chunk.topics == [("architecture", 0.85), ("design", 0.6)]
    assert chunk.topic_method == "supervised"
    assert chunk.topic_confidence == 0.85
    assert chunk.keywords == ["architecture", "design"]
    assert chunk.entities == ["DocKG"]
    assert chunk.embedding == [0.1, 0.2, 0.3]
    assert chunk.run_id == "run-abc"


# ---------------------------------------------------------------------------
# primary_topic property
# ---------------------------------------------------------------------------


def test_primary_topic_with_topics():
    prov = _make_provenance()
    chunk = EntryChunk(
        chunk_id="x",
        text="text",
        provenance=prov,
        topics=[("testing", 0.9), ("implementation", 0.4)],
    )
    assert chunk.primary_topic == "testing"


def test_primary_topic_single_topic():
    prov = _make_provenance()
    chunk = EntryChunk(
        chunk_id="x",
        text="text",
        provenance=prov,
        topics=[("data", 0.5)],
    )
    assert chunk.primary_topic == "data"


def test_primary_topic_empty_returns_unclassified():
    prov = _make_provenance()
    chunk = EntryChunk(
        chunk_id="x",
        text="text",
        provenance=prov,
        topics=[],
    )
    assert chunk.primary_topic == "unclassified"


# ---------------------------------------------------------------------------
# to_node_dict
# ---------------------------------------------------------------------------


def test_to_node_dict_schema():
    prov = SourceProvenance(
        file_path="docs/guide.md",
        char_start=10,
        char_end=90,
        section_title="Overview",
        section_level=2,
        chunk_index=5,
    )
    chunk = EntryChunk(
        chunk_id="pchunk:docs/guide.md:aabbccdd",
        text="Pipeline overview here.",
        provenance=prov,
        topics=[("architecture", 0.7)],
    )
    d = chunk.to_node_dict()

    assert d["id"] == "pchunk:docs/guide.md:aabbccdd"
    assert d["kind"] == "chunk"
    assert d["name"] == "pipeline:0005"
    assert d["title"] == "Overview"
    assert d["file_path"] == "docs/guide.md"
    assert d["char_start"] == 10
    assert d["char_end"] == 90
    assert d["heading_level"] == 2
    assert d["text"] == "Pipeline overview here."


def test_to_node_dict_zero_index_formatting():
    prov = SourceProvenance(file_path="a.md", char_start=0, char_end=10, chunk_index=0)
    chunk = EntryChunk(chunk_id="x", text="t", provenance=prov)
    d = chunk.to_node_dict()
    assert d["name"] == "pipeline:0000"


def test_to_node_dict_none_section():
    prov = SourceProvenance(
        file_path="plain.txt",
        char_start=0,
        char_end=20,
        section_title=None,
        section_level=None,
        chunk_index=2,
    )
    chunk = EntryChunk(chunk_id="x", text="plain text", provenance=prov)
    d = chunk.to_node_dict()
    assert d["title"] is None
    assert d["heading_level"] is None


# ---------------------------------------------------------------------------
# make_chunk_id
# ---------------------------------------------------------------------------


def test_make_chunk_id_format():
    chunk_id = make_chunk_id("docs/intro.md", 0, "Some text content.")
    assert chunk_id.startswith("pchunk:docs/intro.md:")
    parts = chunk_id.split(":")
    # Format: pchunk:<file_path>:<hash8>
    assert parts[0] == "pchunk"
    # The hash part is the last segment (8 hex chars)
    hash_part = parts[-1]
    assert len(hash_part) == 8
    assert all(c in "0123456789abcdef" for c in hash_part)


def test_make_chunk_id_determinism():
    cid1 = make_chunk_id("file.md", 42, "Repeatable text.")
    cid2 = make_chunk_id("file.md", 42, "Repeatable text.")
    assert cid1 == cid2


def test_make_chunk_id_different_inputs_produce_different_ids():
    cid1 = make_chunk_id("file.md", 0, "First text.")
    cid2 = make_chunk_id("file.md", 0, "Second text.")
    assert cid1 != cid2


def test_make_chunk_id_char_start_matters():
    cid1 = make_chunk_id("file.md", 0, "Same text.")
    cid2 = make_chunk_id("file.md", 100, "Same text.")
    assert cid1 != cid2


def test_make_chunk_id_file_path_matters():
    cid1 = make_chunk_id("a.md", 0, "Same text.")
    cid2 = make_chunk_id("b.md", 0, "Same text.")
    assert cid1 != cid2


def test_make_chunk_id_uses_only_first_256_chars():
    """Hash should be identical when only the first 256 chars are the same."""
    base_text = "A" * 256
    long_text = base_text + "extra content that should be ignored"

    cid_base = make_chunk_id("f.md", 0, base_text)
    cid_long = make_chunk_id("f.md", 0, long_text)
    # Both should produce the same hash because [:256] is identical
    assert cid_base == cid_long


def test_make_chunk_id_manual_hash_verification():
    file_path = "notes.md"
    char_start = 10
    text = "Short text."
    payload = f"{file_path}:{char_start}:{text[:256]}"
    expected_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    expected_id = f"pchunk:{file_path}:{expected_digest}"

    result = make_chunk_id(file_path, char_start, text)
    assert result == expected_id
