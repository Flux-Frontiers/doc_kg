"""Tests for manifold.py — ManifoldAnalyzer and ManifoldReport."""

import numpy as np

from doc_kg.manifold import ManifoldAnalyzer, ManifoldReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vectors(n: int, dim: int, seed: int = 0) -> list[list[float]]:
    """Create n random float32 vectors of the given dimension."""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, dim)).astype("float32")
    return X.tolist()


def _make_structured_vectors(n: int, true_dim: int, ambient_dim: int, seed: int = 0) -> list[list[float]]:
    """Create low-rank vectors embedded in ambient_dim-dimensional space."""
    rng = np.random.default_rng(seed)
    # Low-dimensional signal
    Z = rng.standard_normal((n, true_dim)).astype("float32")
    # Random projection matrix
    A = rng.standard_normal((true_dim, ambient_dim)).astype("float32")
    # Embed into ambient space with small noise
    X = Z @ A + rng.standard_normal((n, ambient_dim)).astype("float32") * 0.01
    return X.tolist()


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_analyze_empty_vectors_returns_empty_report():
    analyzer = ManifoldAnalyzer()
    report = analyzer.analyze([])

    assert isinstance(report, ManifoldReport)
    assert report.n_vectors == 0
    assert report.ambient_dim == 0


def test_analyze_empty_has_zero_participation_ratio():
    analyzer = ManifoldAnalyzer()
    report = analyzer.analyze([])
    assert report.participation_ratio == 0.0


def test_analyze_empty_has_zero_twinn_dim():
    analyzer = ManifoldAnalyzer()
    report = analyzer.analyze([])
    assert report.twinn_dim == 0.0


def test_analyze_empty_mrl_mrr_is_empty():
    analyzer = ManifoldAnalyzer()
    report = analyzer.analyze([])
    assert report.mrl_mrr == {}


# ---------------------------------------------------------------------------
# Small random vectors (50 x 32)
# ---------------------------------------------------------------------------


def test_analyze_small_vectors_populates_n_vectors():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.n_vectors == 50


def test_analyze_small_vectors_populates_ambient_dim():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.ambient_dim == 32


def test_analyze_small_vectors_pca_thresholds_populated():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.pca_variance_90 > 0
    assert report.pca_variance_95 > 0
    assert report.pca_variance_99 > 0


def test_analyze_small_vectors_participation_ratio_positive():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.participation_ratio > 0.0


def test_analyze_small_vectors_twinn_positive():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.twinn_dim > 0.0


def test_analyze_small_vectors_mrl_mrr_populated():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    # mrl_dims < ambient_dim (32) should produce entries
    assert len(report.mrl_mrr) > 0


# ---------------------------------------------------------------------------
# PCA variance thresholds are monotonically increasing
# ---------------------------------------------------------------------------


def test_pca_thresholds_monotonically_increasing():
    """90% <= 95% <= 99% variance thresholds."""
    analyzer = ManifoldAnalyzer(pca_max_components=50, mrl_dims=[8])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.pca_variance_90 <= report.pca_variance_95
    assert report.pca_variance_95 <= report.pca_variance_99


def test_pca_thresholds_at_most_ambient_dim():
    analyzer = ManifoldAnalyzer(pca_max_components=50, mrl_dims=[8])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.pca_variance_99 <= report.ambient_dim


# ---------------------------------------------------------------------------
# Participation Ratio
# ---------------------------------------------------------------------------


def test_participation_ratio_greater_than_zero():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8])
    vectors = _make_vectors(40, 32)
    report = analyzer.analyze(vectors)

    assert report.participation_ratio > 0.0


def test_participation_ratio_at_most_ambient_dim():
    """PR should not exceed the ambient dimension."""
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8])
    vectors = _make_vectors(40, 32)
    report = analyzer.analyze(vectors)

    assert report.participation_ratio <= report.ambient_dim


# ---------------------------------------------------------------------------
# TwoNN
# ---------------------------------------------------------------------------


def test_twinn_returns_positive_dimension():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8])
    vectors = _make_vectors(50, 32)
    report = analyzer.analyze(vectors)

    assert report.twinn_dim > 0.0


def test_twinn_too_few_vectors_returns_zero():
    """With fewer than 10 vectors, TwoNN should return 0."""
    analyzer = ManifoldAnalyzer(pca_max_components=8, mrl_dims=[4])
    vectors = _make_vectors(5, 8)
    report = analyzer.analyze(vectors)

    assert report.twinn_dim == 0.0


# ---------------------------------------------------------------------------
# MRL truncation quality
# ---------------------------------------------------------------------------


def test_mrl_mrr_full_dim_is_one():
    """Full dimension MRR should be 1.0 (ground truth vs ground truth)."""
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(30, 32)
    report = analyzer.analyze(vectors)

    # The full dim key should be 1.0
    dim = report.ambient_dim
    assert dim in report.mrl_mrr
    assert report.mrl_mrr[dim] == 1.0


def test_mrl_mrr_truncated_dims_between_zero_and_one():
    analyzer = ManifoldAnalyzer(pca_max_components=32, mrl_dims=[8, 16])
    vectors = _make_vectors(30, 32)
    report = analyzer.analyze(vectors)

    for dim, mrr in report.mrl_mrr.items():
        assert 0.0 <= mrr <= 1.0, f"MRR at dim {dim} out of range: {mrr}"


def test_mrl_mrr_expected_dim_keys():
    """Dimensions in mrl_dims that are < ambient_dim should appear in results."""
    analyzer = ManifoldAnalyzer(pca_max_components=64, mrl_dims=[8, 16, 32])
    vectors = _make_vectors(30, 64)
    report = analyzer.analyze(vectors)

    for dim in (8, 16, 32):
        assert dim in report.mrl_mrr, f"Expected dim {dim} in mrl_mrr"


def test_mrl_mrr_skips_dims_equal_to_or_greater_than_ambient():
    analyzer = ManifoldAnalyzer(pca_max_components=16, mrl_dims=[8, 32, 64])
    vectors = _make_vectors(20, 16)
    report = analyzer.analyze(vectors)

    # dim=8 should appear; dim=32 and 64 should NOT appear (>= ambient_dim 16)
    assert 8 in report.mrl_mrr
    assert 32 not in report.mrl_mrr
    assert 64 not in report.mrl_mrr


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_returns_non_empty_string():
    analyzer = ManifoldAnalyzer(pca_max_components=16, mrl_dims=[8])
    vectors = _make_vectors(20, 16)
    report = analyzer.analyze(vectors)

    formatted = analyzer.format_report(report)
    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_format_report_contains_key_sections():
    analyzer = ManifoldAnalyzer(pca_max_components=16, mrl_dims=[8])
    vectors = _make_vectors(20, 16)
    report = analyzer.analyze(vectors)

    formatted = analyzer.format_report(report)
    assert "Manifold Analysis Report" in formatted
    assert "PCA" in formatted
    assert "Participation Ratio" in formatted
    assert "TwoNN" in formatted
    assert "MRL" in formatted


def test_format_report_empty_report():
    analyzer = ManifoldAnalyzer()
    report = ManifoldReport()  # all zeros
    formatted = analyzer.format_report(report)

    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_format_report_contains_n_vectors():
    analyzer = ManifoldAnalyzer(pca_max_components=16, mrl_dims=[8])
    vectors = _make_vectors(25, 16)
    report = analyzer.analyze(vectors)

    formatted = analyzer.format_report(report)
    assert "25" in formatted
