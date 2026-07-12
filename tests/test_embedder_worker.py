"""Tests for embedder_worker.py — PIPELINE_MODEL and the kg_utils re-export.

CorpusEmbedder / EmbeddingCache / _embed_shard now live in
kg_utils.corpus_embedder (see CHANGELOG.md); their unit coverage lives there.
This module only tests doc_kg's own surface: PIPELINE_MODEL and that the
re-export resolves to the canonical kg_utils implementation.
"""

from pathlib import Path

import kg_utils.corpus_embedder as _kg_corpus_embedder

from doc_kg.embedder_worker import PIPELINE_MODEL, CorpusEmbedder, EmbeddingCache

# ---------------------------------------------------------------------------
# PIPELINE_MODEL constant
# ---------------------------------------------------------------------------


def test_pipeline_model_constant_value():
    assert PIPELINE_MODEL == "BAAI/bge-small-en-v1.5"


def test_pipeline_model_is_string():
    assert isinstance(PIPELINE_MODEL, str)


def test_pipeline_model_is_non_empty():
    assert len(PIPELINE_MODEL) > 0


# ---------------------------------------------------------------------------
# Re-export identity — CorpusEmbedder/EmbeddingCache must be the actual
# kg_utils classes, not a diverged local copy.
# ---------------------------------------------------------------------------


def test_corpus_embedder_is_kg_utils_class():
    assert CorpusEmbedder is _kg_corpus_embedder.CorpusEmbedder


def test_embedding_cache_is_kg_utils_class():
    assert EmbeddingCache is _kg_corpus_embedder.EmbeddingCache


def test_corpus_embedder_constructs_with_pipeline_model():
    embedder = CorpusEmbedder(PIPELINE_MODEL, n_workers=2, batch_size=32, device="cpu")
    assert embedder.model_name == PIPELINE_MODEL
    assert embedder.device == "cpu"


def test_save_load_cache_roundtrip_via_reexport(tmp_path):
    """Smoke test that the re-exported save_cache/load_cache still work end to end."""
    cache = EmbeddingCache(
        model="test-model",
        dim=4,
        texts=["a", "b"],
        vectors=[[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
        metadata=[{"file_path": "a.md"}, {"file_path": "b.md"}],
    )
    out: Path = tmp_path / "embeddings.json"
    CorpusEmbedder.save_cache(cache, out)
    loaded = CorpusEmbedder.load_cache(out)

    assert loaded.model == cache.model
    assert loaded.texts == cache.texts
    assert loaded.n_vectors == 2
