"""Tests for embedder_worker.py — PIPELINE_MODEL, EmbeddingCache, save/load roundtrip."""

import json

from doc_kg.embedder_worker import PIPELINE_MODEL, CorpusEmbedder, EmbeddingCache

# ---------------------------------------------------------------------------
# PIPELINE_MODEL constant
# ---------------------------------------------------------------------------


def test_pipeline_model_constant_value():
    assert PIPELINE_MODEL == "nomic-ai/nomic-embed-text-v1"


def test_pipeline_model_is_string():
    assert isinstance(PIPELINE_MODEL, str)


def test_pipeline_model_is_non_empty():
    assert len(PIPELINE_MODEL) > 0


# ---------------------------------------------------------------------------
# EmbeddingCache creation
# ---------------------------------------------------------------------------


def test_embedding_cache_basic_creation():
    cache = EmbeddingCache(
        model="test-model",
        dim=32,
        texts=["hello", "world"],
        vectors=[[0.1] * 32, [0.2] * 32],
    )
    assert cache.model == "test-model"
    assert cache.dim == 32
    assert cache.texts == ["hello", "world"]
    assert len(cache.vectors) == 2


def test_embedding_cache_n_vectors_property():
    vectors = [[float(i)] * 8 for i in range(5)]
    cache = EmbeddingCache(
        model="m",
        dim=8,
        texts=[f"text{i}" for i in range(5)],
        vectors=vectors,
    )
    assert cache.n_vectors == 5


def test_embedding_cache_n_vectors_empty():
    cache = EmbeddingCache(model="m", dim=0, texts=[], vectors=[])
    assert cache.n_vectors == 0


def test_embedding_cache_n_vectors_matches_vectors_list():
    n = 7
    cache = EmbeddingCache(
        model="m",
        dim=4,
        texts=[f"t{i}" for i in range(n)],
        vectors=[[0.0] * 4 for _ in range(n)],
    )
    assert cache.n_vectors == n


def test_embedding_cache_auto_generates_created_at():
    """created_at is auto-generated when left blank."""
    cache = EmbeddingCache(model="m", dim=4, texts=[], vectors=[])
    assert cache.created_at != ""
    assert len(cache.created_at) > 0


def test_embedding_cache_auto_created_at_is_iso_format():
    """created_at should be parseable as an ISO timestamp."""
    from datetime import datetime

    cache = EmbeddingCache(model="m", dim=4, texts=[], vectors=[])
    # Should not raise
    dt = datetime.fromisoformat(cache.created_at)
    assert dt is not None


def test_embedding_cache_explicit_created_at_preserved():
    ts = "2025-01-15T12:00:00+00:00"
    cache = EmbeddingCache(model="m", dim=4, texts=[], vectors=[], created_at=ts)
    assert cache.created_at == ts


def test_embedding_cache_default_metadata_is_empty_list():
    cache = EmbeddingCache(model="m", dim=4, texts=["t"], vectors=[[0.0] * 4])
    assert cache.metadata == []


def test_embedding_cache_with_metadata():
    meta = [{"file_path": "a.md"}, {"file_path": "b.md"}]
    cache = EmbeddingCache(
        model="m",
        dim=4,
        texts=["t1", "t2"],
        vectors=[[0.0] * 4, [1.0] * 4],
        metadata=meta,
    )
    assert cache.metadata == meta


# ---------------------------------------------------------------------------
# save_cache / load_cache roundtrip
# ---------------------------------------------------------------------------


def _make_cache(n: int = 5, dim: int = 8) -> EmbeddingCache:
    """Create a synthetic EmbeddingCache for testing."""
    texts = [f"text number {i}" for i in range(n)]
    vectors = [[float(i * 0.1 + j * 0.01) for j in range(dim)] for i in range(n)]
    metadata = [{"index": i, "source": f"doc{i}.md"} for i in range(n)]
    return EmbeddingCache(
        model="test-model-v1",
        dim=dim,
        texts=texts,
        vectors=vectors,
        metadata=metadata,
        created_at="2025-04-01T00:00:00+00:00",
    )


def test_save_cache_creates_file(tmp_path):
    cache = _make_cache()
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    assert out.exists()


def test_save_cache_creates_parent_dirs(tmp_path):
    cache = _make_cache()
    out = tmp_path / "nested" / "dir" / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    assert out.exists()


def test_save_cache_writes_valid_json(tmp_path):
    cache = _make_cache()
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)

    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_load_cache_roundtrip_model(tmp_path):
    cache = _make_cache()
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.model == cache.model


def test_load_cache_roundtrip_dim(tmp_path):
    cache = _make_cache(dim=16)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.dim == 16


def test_load_cache_roundtrip_texts(tmp_path):
    cache = _make_cache(n=3)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.texts == cache.texts


def test_load_cache_roundtrip_vectors(tmp_path):
    cache = _make_cache(n=4, dim=8)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert len(loaded.vectors) == 4
    for orig, loaded_v in zip(cache.vectors, loaded.vectors):
        assert len(loaded_v) == 8
        for a, b in zip(orig, loaded_v):
            assert abs(a - b) < 1e-6


def test_load_cache_roundtrip_metadata(tmp_path):
    cache = _make_cache(n=3)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.metadata == cache.metadata


def test_load_cache_roundtrip_n_vectors(tmp_path):
    cache = _make_cache(n=6)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.n_vectors == 6


def test_load_cache_roundtrip_created_at(tmp_path):
    cache = _make_cache()
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.created_at == cache.created_at


def test_save_load_empty_cache(tmp_path):
    cache = EmbeddingCache(
        model="empty-model",
        dim=0,
        texts=[],
        vectors=[],
        created_at="2025-01-01T00:00:00+00:00",
    )
    out = tmp_path / "empty.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.n_vectors == 0
    assert loaded.texts == []
    assert loaded.model == "empty-model"


def test_save_cache_json_structure(tmp_path):
    """Verify the JSON file contains all expected top-level keys."""
    cache = _make_cache(n=2)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)

    with open(out, encoding="utf-8") as f:
        data = json.load(f)

    for key in ("model", "dim", "n_vectors", "created_at", "texts", "metadata", "embeddings"):
        assert key in data, f"Missing key in saved JSON: {key}"


def test_save_cache_n_vectors_matches(tmp_path):
    """Saved n_vectors field should match len(vectors)."""
    cache = _make_cache(n=3)
    out = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)

    with open(out, encoding="utf-8") as f:
        data = json.load(f)

    assert data["n_vectors"] == 3
    assert len(data["embeddings"]) == 3
