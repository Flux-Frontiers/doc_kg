#!/usr/bin/env python3
"""
manifold.py

ManifoldAnalyzer — Stage 4 of the multipass analysis pipeline.

Performs intrinsic dimensionality estimation and MRL (Matryoshka
Representation Learning) truncation quality analysis on corpus embeddings.

Analyses:
- PCA elbow: explained variance curve, knee detection
- Participation Ratio: effective dimensionality from eigenvalue spectrum
- TwoNN: Two-Nearest-Neighbors intrinsic dimensionality (Facco et al. 2017)
- MRL truncation quality: MRR@10 at various truncated dimensions

Usage::

    from doc_kg.manifold import ManifoldAnalyzer
    from doc_kg.embedder_worker import CorpusEmbedder

    cache = CorpusEmbedder.load_cache(Path("embeddings.json"))
    analyzer = ManifoldAnalyzer()
    report = analyzer.analyze(cache.vectors)
    print(report)

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ManifoldReport:
    """Results from manifold analysis.

    :param n_vectors: Number of vectors analyzed.
    :param ambient_dim: Full embedding dimension.
    :param pca_variance_90: Dimensions for 90% explained variance.
    :param pca_variance_95: Dimensions for 95% explained variance.
    :param pca_variance_99: Dimensions for 99% explained variance.
    :param participation_ratio: PR = (sum lambda_i)^2 / sum(lambda_i^2).
    :param twinn_dim: TwoNN intrinsic dimensionality estimate.
    :param mrl_mrr: MRR@10 at various truncated dimensions.
    :param pca_explained_variance: First N explained variance ratios.
    """

    n_vectors: int = 0
    ambient_dim: int = 0
    pca_variance_90: int = 0
    pca_variance_95: int = 0
    pca_variance_99: int = 0
    participation_ratio: float = 0.0
    twinn_dim: float = 0.0
    mrl_mrr: dict[int, float] = field(default_factory=dict)
    pca_explained_variance: list[float] = field(default_factory=list)


class ManifoldAnalyzer:
    """Intrinsic dimensionality and MRL truncation analysis.

    :param pca_max_components: Maximum PCA components to compute.
    :param mrl_dims: Truncation dimensions for MRL quality check.
    :param mrr_k: k for MRR@k evaluation.
    """

    def __init__(
        self,
        *,
        pca_max_components: int = 256,
        mrl_dims: list[int] | None = None,
        mrr_k: int = 10,
    ) -> None:
        self.pca_max_components = pca_max_components
        self.mrl_dims = mrl_dims or [32, 64, 128, 256, 512]
        self.mrr_k = mrr_k

    def analyze(self, vectors: list[list[float]]) -> ManifoldReport:
        """Run full manifold analysis on embedding vectors.

        :param vectors: List of float32 vectors.
        :return: :class:`ManifoldReport` with all analysis results.
        """
        if not vectors:
            return ManifoldReport()

        X = np.asarray(vectors, dtype="float32")
        n, d = X.shape

        report = ManifoldReport(n_vectors=n, ambient_dim=d)

        # PCA analysis
        try:
            self._pca_analysis(X, report)
        except Exception as exc:
            logger.warning("PCA analysis failed: %s", exc)

        # Participation Ratio
        try:
            report.participation_ratio = self._participation_ratio(X)
        except Exception as exc:
            logger.warning("Participation ratio failed: %s", exc)

        # TwoNN
        try:
            report.twinn_dim = self._twinn(X)
        except Exception as exc:
            logger.warning("TwoNN failed: %s", exc)

        # MRL truncation quality
        try:
            report.mrl_mrr = self._mrl_mrr(X)
        except Exception as exc:
            logger.warning("MRL analysis failed: %s", exc)

        return report

    def _pca_analysis(self, X: np.ndarray, report: ManifoldReport) -> None:
        """PCA explained variance analysis."""
        from sklearn.decomposition import PCA  # pylint: disable=import-outside-toplevel

        n, d = X.shape
        n_components = min(self.pca_max_components, n, d)
        pca = PCA(n_components=n_components)
        pca.fit(X)

        cum_var = np.cumsum(pca.explained_variance_ratio_)
        report.pca_explained_variance = pca.explained_variance_ratio_[:50].tolist()

        for threshold, attr in [
            (0.90, "pca_variance_90"),
            (0.95, "pca_variance_95"),
            (0.99, "pca_variance_99"),
        ]:
            idx = np.searchsorted(cum_var, threshold)
            setattr(report, attr, int(idx) + 1 if idx < len(cum_var) else n_components)

    def _participation_ratio(self, X: np.ndarray) -> float:
        """Participation Ratio: PR = (sum lambda_i)^2 / sum(lambda_i^2).

        Measures the effective number of dimensions used by the data.
        """
        from sklearn.decomposition import PCA  # pylint: disable=import-outside-toplevel

        n, d = X.shape
        n_components = min(self.pca_max_components, n, d)
        pca = PCA(n_components=n_components)
        pca.fit(X)

        eigenvalues = pca.explained_variance_
        sum_lambda = float(np.sum(eigenvalues))
        sum_lambda_sq = float(np.sum(eigenvalues**2))

        if sum_lambda_sq == 0:
            return 0.0
        return round(sum_lambda**2 / sum_lambda_sq, 2)

    def _twinn(self, X: np.ndarray) -> float:
        """Two-Nearest-Neighbors intrinsic dimensionality estimator.

        Facco et al. (2017): Estimating the intrinsic dimension of datasets
        by a minimal neighborhood information.

        Uses the ratio of second-nearest to nearest neighbor distances.
        """
        from sklearn.neighbors import (  # pylint: disable=import-outside-toplevel
            NearestNeighbors,
        )

        n = X.shape[0]
        if n < 10:
            return 0.0

        nn = NearestNeighbors(n_neighbors=3, metric="cosine")
        nn.fit(X)
        distances, _ = nn.kneighbors(X)

        # distances[:, 0] is always 0 (self), [:, 1] is nearest, [:, 2] is second nearest
        r1 = distances[:, 1]
        r2 = distances[:, 2]

        # Filter out zero distances to avoid division by zero
        mask = r1 > 1e-10
        if mask.sum() < 5:
            return 0.0

        mu = r2[mask] / r1[mask]
        mu_sorted = np.sort(mu)

        # Maximum likelihood estimate: d = n / sum(log(mu_i))
        log_mu = np.log(mu_sorted)
        log_mu = log_mu[np.isfinite(log_mu)]

        if len(log_mu) == 0 or np.sum(log_mu) == 0:
            return 0.0

        d_est = len(log_mu) / np.sum(log_mu)
        return round(float(d_est), 2)

    def _mrl_mrr(self, X: np.ndarray) -> dict[int, float]:
        """MRL truncation quality: MRR@k at various truncated dimensions.

        Compares retrieval rankings at truncated dims vs full dimension.
        """
        n, d = X.shape
        if n < self.mrr_k + 1:
            return {}

        # Full-dimension cosine similarity rankings (ground truth)
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        X_normed = X / norms
        full_sim = X_normed @ X_normed.T

        # For each query, get top-k ground truth neighbors (excluding self)
        np.fill_diagonal(full_sim, -1.0)
        gt_rankings = np.argsort(-full_sim, axis=1)[:, : self.mrr_k]

        results: dict[int, float] = {}

        for dim in self.mrl_dims:
            if dim >= d:
                continue

            # Truncate to first `dim` dimensions and re-normalize
            X_trunc = X[:, :dim]
            t_norms = np.linalg.norm(X_trunc, axis=1, keepdims=True)
            t_norms = np.maximum(t_norms, 1e-10)
            X_t_normed = X_trunc / t_norms
            trunc_sim = X_t_normed @ X_t_normed.T
            np.fill_diagonal(trunc_sim, -1.0)
            trunc_rankings = np.argsort(-trunc_sim, axis=1)[:, : self.mrr_k]

            # Compute MRR: for each query, find rank of the top-1 GT neighbor
            # in the truncated rankings
            rr_sum = 0.0
            for i in range(n):
                gt_top1 = gt_rankings[i, 0]
                ranks = np.where(trunc_rankings[i] == gt_top1)[0]
                if len(ranks) > 0:
                    rr_sum += 1.0 / (ranks[0] + 1)

            mrr = rr_sum / n
            results[dim] = round(mrr, 4)

        # Add full dimension for reference
        results[d] = 1.0

        return results

    def format_report(self, report: ManifoldReport) -> str:
        """Format a manifold report as human-readable text.

        :param report: Analysis results.
        :return: Formatted string.
        """
        lines = [
            "Manifold Analysis Report",
            "=" * 40,
            f"Vectors:          {report.n_vectors}",
            f"Ambient dim:      {report.ambient_dim}",
            "",
            "PCA Explained Variance:",
            f"  90% at:         {report.pca_variance_90} dims",
            f"  95% at:         {report.pca_variance_95} dims",
            f"  99% at:         {report.pca_variance_99} dims",
            "",
            f"Participation Ratio: {report.participation_ratio}",
            f"TwoNN dimension:    {report.twinn_dim}",
            "",
            "MRL Truncation Quality (MRR@10):",
        ]
        for dim in sorted(report.mrl_mrr):
            lines.append(f"  {dim:>4d}-dim: {report.mrl_mrr[dim]:.4f}")

        return "\n".join(lines)
