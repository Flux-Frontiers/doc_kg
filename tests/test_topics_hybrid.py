"""Tests for hybrid classification additions to topics.py."""

from doc_kg.topics import TopicExtractor, TopicMatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_random_embeddings(n: int = 20, dim: int = 32) -> list[list[float]]:
    """Create deterministic pseudo-random embeddings without numpy dependency."""
    import math

    result = []
    for i in range(n):
        # Use a simple deterministic sequence to avoid importing numpy
        vec = [math.sin(i * 0.3 + j * 0.7) for j in range(dim)]
        # Normalize
        norm = math.sqrt(sum(v * v for v in vec))
        vec = [v / norm for v in vec] if norm > 0 else vec
        result.append(vec)
    return result


# ---------------------------------------------------------------------------
# fit_clusters
# ---------------------------------------------------------------------------


def test_fit_clusters_sets_kmeans_attribute():
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=16, dim=16)
    extractor.fit_clusters(embeddings, n_clusters=4)
    assert hasattr(extractor, "_kmeans")
    assert extractor._kmeans is not None


def test_fit_clusters_with_fewer_docs_than_clusters():
    """Should not fail when n_docs < n_clusters — actual_k is clamped."""
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=3, dim=8)
    extractor.fit_clusters(embeddings, n_clusters=10)
    assert hasattr(extractor, "_kmeans")


def test_fit_clusters_creates_cluster_labels():
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=12, dim=8)
    extractor.fit_clusters(embeddings, n_clusters=3)
    assert hasattr(extractor, "_cluster_labels")
    assert len(extractor._cluster_labels) == 3


def test_fit_clusters_custom_labels():
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=10, dim=8)
    labels = ["topic_a", "topic_b", "topic_c"]
    extractor.fit_clusters(embeddings, n_clusters=3, labels=labels)
    assert extractor._cluster_labels == labels


def test_fit_clusters_auto_labels_when_not_provided():
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=10, dim=8)
    extractor.fit_clusters(embeddings, n_clusters=3)
    for label in extractor._cluster_labels:
        assert label.startswith("cluster_")


# ---------------------------------------------------------------------------
# classify_hybrid — "supervised" path
# ---------------------------------------------------------------------------


def test_classify_hybrid_returns_supervised_for_clear_topic():
    """Text with strong keyword match for a default topic should use supervised path."""
    extractor = TopicExtractor()
    text = "pytest coverage assertion test fixture failing"
    matches, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.2)

    assert method == "supervised"
    assert len(matches) > 0
    assert matches[0].score >= 0.2


def test_classify_hybrid_supervised_architecture_text():
    extractor = TopicExtractor()
    text = "system architecture design pattern module api"
    matches, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.2)

    assert method == "supervised"
    assert any(m.topic == "architecture" for m in matches)


def test_classify_hybrid_supervised_returns_topic_match_list():
    extractor = TopicExtractor()
    text = "deploy release build ci cd pipeline"
    matches, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.2)

    assert isinstance(matches, list)
    assert all(isinstance(m, TopicMatch) for m in matches)


# ---------------------------------------------------------------------------
# classify_hybrid — "fallback" path
# ---------------------------------------------------------------------------


def test_classify_hybrid_returns_fallback_for_gibberish():
    """Text with no recognisable keywords and no fitted clusters => fallback."""
    extractor = TopicExtractor()
    # Gibberish that matches no topics and produces no meaningful keywords
    text = "zzz qqq mmm zzz qqq mmm"
    matches, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.9)

    assert method == "fallback"


def test_classify_hybrid_fallback_returns_list():
    extractor = TopicExtractor()
    text = "xyzzy quux blorph fleem"
    matches, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.99)

    assert isinstance(matches, list)
    assert method == "fallback"


def test_classify_hybrid_empty_text_returns_fallback():
    extractor = TopicExtractor()
    matches, method = extractor.classify_hybrid("", embedding=None, supervised_threshold=0.3)
    assert method == "fallback"
    assert matches == []


# ---------------------------------------------------------------------------
# classify_hybrid — "unsupervised" path
# ---------------------------------------------------------------------------


def test_classify_hybrid_uses_unsupervised_when_clusters_fitted():
    """After fit_clusters, text that fails supervised should use unsupervised path."""
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=20, dim=16)
    extractor.fit_clusters(embeddings, n_clusters=4)

    # Use a very high threshold to force supervised to fail
    text = "test assertion pytest coverage"  # would normally be supervised
    query_embedding = embeddings[0]
    matches, method = extractor.classify_hybrid(
        text,
        embedding=query_embedding,
        supervised_threshold=0.999,
    )

    assert method == "unsupervised"
    assert len(matches) == 1
    assert matches[0].topic.startswith("cluster:")


def test_classify_hybrid_unsupervised_topic_has_positive_score():
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=20, dim=16)
    extractor.fit_clusters(embeddings, n_clusters=4)

    text = "random tokens that will not match"
    query_embedding = embeddings[5]
    matches, method = extractor.classify_hybrid(
        text,
        embedding=query_embedding,
        supervised_threshold=0.999,
    )

    if method == "unsupervised":
        assert matches[0].score > 0


def test_classify_hybrid_unsupervised_requires_embedding():
    """Without an embedding, unsupervised path is skipped even with clusters fitted."""
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=20, dim=16)
    extractor.fit_clusters(embeddings, n_clusters=4)

    # No embedding provided — can't do unsupervised
    matches, method = extractor.classify_hybrid(
        "xyzzy quux",
        embedding=None,
        supervised_threshold=0.999,
    )
    # Must be supervised or fallback, not unsupervised
    assert method in ("supervised", "fallback")


# ---------------------------------------------------------------------------
# supervised_threshold parameter
# ---------------------------------------------------------------------------


def test_high_threshold_forces_unsupervised_or_fallback():
    """A threshold of 1.0 means supervised never wins."""
    extractor = TopicExtractor()
    embeddings = _make_random_embeddings(n=16, dim=16)
    extractor.fit_clusters(embeddings, n_clusters=4)

    text = "architecture design system pattern"
    embedding = embeddings[0]
    _, method = extractor.classify_hybrid(text, embedding=embedding, supervised_threshold=1.0)
    assert method in ("unsupervised", "fallback")


def test_low_threshold_accepts_supervised_easily():
    """A threshold of 0.0 means any supervised result wins."""
    extractor = TopicExtractor()
    text = "architecture system design"
    _, method = extractor.classify_hybrid(text, embedding=None, supervised_threshold=0.0)
    assert method == "supervised"


# ---------------------------------------------------------------------------
# classify_hybrid return type contract
# ---------------------------------------------------------------------------


def test_classify_hybrid_always_returns_tuple_of_two():
    extractor = TopicExtractor()
    result = extractor.classify_hybrid("some text here", embedding=None)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_classify_hybrid_method_is_one_of_three_values():
    extractor = TopicExtractor()
    _, method = extractor.classify_hybrid("some text here", embedding=None)
    assert method in ("supervised", "unsupervised", "fallback")
