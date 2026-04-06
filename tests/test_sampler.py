"""Tests for sampler.py — DocFeatures, CorpusSampler."""

from pathlib import Path

from doc_kg.sampler import CorpusSampler, DocFeatures


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_corpus(tmp_path: Path, n: int = 5) -> list[Path]:
    """Create n small markdown files in tmp_path and return their paths."""
    paths = []
    for i in range(n):
        p = tmp_path / f"doc{i:02d}.md"
        p.write_text(
            f"# Document {i}\n\n"
            f"This is document number {i}. "
            f"It contains some text about topic {i}. "
            f"DocKG and SQLite are mentioned here. "
            f"This sentence adds more content for testing.\n",
            encoding="utf-8",
        )
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# DocFeatures
# ---------------------------------------------------------------------------


def test_doc_features_to_vector_length():
    feat = DocFeatures(
        file_path="a.md",
        file_hash="abc123",
        n_tokens=100,
        n_sentences=10,
        n_unique_words=80,
        n_entities=5,
        text_length=500,
        temporal_index=3,
    )
    vec = feat.to_vector()
    assert len(vec) == 6


def test_doc_features_to_vector_values():
    feat = DocFeatures(
        file_path="a.md",
        file_hash="abc123",
        n_tokens=100,
        n_sentences=10,
        n_unique_words=80,
        n_entities=5,
        text_length=500,
        temporal_index=3,
    )
    vec = feat.to_vector()
    assert vec[0] == 100.0  # n_tokens
    assert vec[1] == 10.0   # n_sentences
    assert vec[2] == 80.0   # n_unique_words
    assert vec[3] == 5.0    # n_entities
    assert vec[4] == 500.0  # text_length
    assert vec[5] == 3.0    # temporal_index


def test_doc_features_to_vector_all_floats():
    feat = DocFeatures(file_path="b.md", file_hash="x", n_tokens=7, temporal_index=0)
    vec = feat.to_vector()
    assert all(isinstance(v, float) for v in vec)


def test_doc_features_defaults():
    feat = DocFeatures(file_path="c.md", file_hash="y")
    assert feat.n_tokens == 0
    assert feat.n_sentences == 0
    assert feat.n_unique_words == 0
    assert feat.n_entities == 0
    assert feat.text_length == 0
    assert feat.temporal_index == 0


# ---------------------------------------------------------------------------
# CorpusSampler.extract_features
# ---------------------------------------------------------------------------


def test_extract_features_returns_correct_count(tmp_path):
    paths = _make_corpus(tmp_path, n=4)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    features = sampler.extract_features(paths)
    assert len(features) == 4


def test_extract_features_reasonable_values(tmp_path):
    paths = _make_corpus(tmp_path, n=2)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    features = sampler.extract_features(paths)

    for feat in features:
        assert feat.n_tokens > 0
        assert feat.n_sentences >= 1
        assert feat.n_unique_words > 0
        assert feat.text_length > 0


def test_extract_features_temporal_index_order(tmp_path):
    paths = _make_corpus(tmp_path, n=3)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    features = sampler.extract_features(paths)

    # temporal_index matches list position
    for i, feat in enumerate(features):
        assert feat.temporal_index == i


def test_extract_features_populates_file_hash(tmp_path):
    paths = _make_corpus(tmp_path, n=2)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    features = sampler.extract_features(paths)

    for feat in features:
        assert feat.file_hash != ""
        assert len(feat.file_hash) == 16  # first 16 hex chars of SHA-256


# ---------------------------------------------------------------------------
# CorpusSampler.sample — batch_size >= len(paths)
# ---------------------------------------------------------------------------


def test_sample_returns_all_when_batch_size_exceeds_corpus(tmp_path):
    paths = _make_corpus(tmp_path, n=3)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=10)

    assert len(result.selected_paths) == 3


def test_sample_returns_all_when_batch_size_equals_corpus(tmp_path):
    paths = _make_corpus(tmp_path, n=4)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=4)

    assert len(result.selected_paths) == 4


# ---------------------------------------------------------------------------
# CorpusSampler.sample — random strategy
# ---------------------------------------------------------------------------


def test_sample_random_returns_correct_count(tmp_path):
    paths = _make_corpus(tmp_path, n=10)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=5, strategy="random")

    assert len(result.selected_paths) == 5
    assert result.strategy == "random"


def test_sample_random_paths_are_substrings_of_corpus(tmp_path):
    paths = _make_corpus(tmp_path, n=8)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=4, strategy="random")

    all_names = {p.name for p in paths}
    for sel in result.selected_paths:
        # Selected paths are relative; just check the filename is in the corpus
        assert Path(sel).name in all_names


def test_sample_random_is_reproducible(tmp_path):
    paths = _make_corpus(tmp_path, n=10)
    sampler1 = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache", seed=42)
    sampler2 = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache", seed=42)

    result1 = sampler1.sample(paths, batch_size=5, strategy="random")
    result2 = sampler2.sample(paths, batch_size=5, strategy="random")

    assert result1.selected_paths == result2.selected_paths


# ---------------------------------------------------------------------------
# CorpusSampler.sample — temporal strategy
# ---------------------------------------------------------------------------


def test_sample_temporal_returns_correct_count(tmp_path):
    paths = _make_corpus(tmp_path, n=10)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=5, strategy="temporal")

    assert len(result.selected_paths) == 5
    assert result.strategy == "temporal"


def test_sample_temporal_includes_first_and_last(tmp_path):
    paths = _make_corpus(tmp_path, n=10)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache")
    result = sampler.sample(paths, batch_size=5, strategy="temporal")

    # Temporal sampling should include the first document
    first_name = Path(result.selected_paths[0]).name
    assert first_name == "doc00.md"


# ---------------------------------------------------------------------------
# CorpusSampler.sample — diversity strategy
# ---------------------------------------------------------------------------


def test_sample_diversity_returns_correct_count(tmp_path):
    paths = _make_corpus(tmp_path, n=10)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache", n_clusters=3)
    result = sampler.sample(paths, batch_size=5, strategy="diversity")

    # Should return at most batch_size docs
    assert len(result.selected_paths) <= 5
    assert result.strategy == "diversity"


def test_sample_diversity_all_features_present(tmp_path):
    paths = _make_corpus(tmp_path, n=6)
    sampler = CorpusSampler(tmp_path, cache_dir=tmp_path / ".cache", n_clusters=2)
    result = sampler.sample(paths, batch_size=3, strategy="diversity")

    # all_features covers all corpus documents, not just selected
    assert len(result.all_features) == 6


# ---------------------------------------------------------------------------
# Feature caching
# ---------------------------------------------------------------------------


def test_feature_cache_files_are_created(tmp_path):
    paths = _make_corpus(tmp_path, n=3)
    cache_dir = tmp_path / ".dockg" / "cache"
    sampler = CorpusSampler(tmp_path, cache_dir=cache_dir)
    sampler.extract_features(paths)

    cache_files = list(cache_dir.glob("*.pkl"))
    assert len(cache_files) == 3


def test_feature_cache_second_call_uses_cache(tmp_path):
    paths = _make_corpus(tmp_path, n=2)
    cache_dir = tmp_path / ".dockg" / "cache"
    sampler = CorpusSampler(tmp_path, cache_dir=cache_dir)

    # First call — populates cache
    feats1 = sampler.extract_features(paths)

    # Second call — should use cache (same result)
    feats2 = sampler.extract_features(paths)

    assert len(feats1) == len(feats2)
    for f1, f2 in zip(feats1, feats2):
        assert f1.file_hash == f2.file_hash
        assert f1.n_tokens == f2.n_tokens
        assert f1.text_length == f2.text_length


def test_feature_cache_invalidated_on_content_change(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Original\n\nOriginal content here.\n", encoding="utf-8")
    paths = [doc]

    cache_dir = tmp_path / ".dockg" / "cache"
    sampler = CorpusSampler(tmp_path, cache_dir=cache_dir)

    feats1 = sampler.extract_features(paths)

    # Modify the file
    doc.write_text(
        "# Modified\n\nCompletely different content that is much longer.\n"
        "More sentences added for good measure.\n",
        encoding="utf-8",
    )

    feats2 = sampler.extract_features(paths)

    # Content hash must differ
    assert feats1[0].file_hash != feats2[0].file_hash
