#!/usr/bin/env python3
"""
sampler.py

CorpusSampler — Phase 1 of the multipass analysis pipeline.

Extracts NLP features from corpus documents, clusters them for diversity,
and returns representative samples for batch processing.

Features extracted per document:
- Token count, sentence count, unique word count
- Entity count (titlecase/acronym heuristic)
- Keyword density
- Text length
- Temporal index (file sort-order position)

Supports pickle-based feature caching with file-hash invalidation for
5-10x speedup on subsequent runs.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Reuse sentence splitter from chunker
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\'\(\[])")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,30}")
_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}"
    r"|[A-Z]{2,}[A-Z0-9]*"
    r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*)\b"
)


@dataclass
class DocFeatures:
    """NLP feature vector for a single document.

    :param file_path: Corpus-relative path.
    :param file_hash: SHA-256 content hash (first 16 hex chars).
    :param n_tokens: Total token count.
    :param n_sentences: Sentence count.
    :param n_unique_words: Unique lowercased word count.
    :param n_entities: Entity count (titlecase/acronym heuristic).
    :param text_length: Character count.
    :param temporal_index: Position in corpus file-sort order.
    """

    file_path: str
    file_hash: str
    n_tokens: int = 0
    n_sentences: int = 0
    n_unique_words: int = 0
    n_entities: int = 0
    text_length: int = 0
    temporal_index: int = 0

    def to_vector(self) -> list[float]:
        """Return a numeric feature vector for clustering."""
        return [
            float(self.n_tokens),
            float(self.n_sentences),
            float(self.n_unique_words),
            float(self.n_entities),
            float(self.text_length),
            float(self.temporal_index),
        ]


@dataclass
class SampleResult:
    """Result of a diversity sampling run.

    :param selected_paths: Corpus-relative paths of selected documents.
    :param all_features: Features for all documents (not just sampled).
    :param cluster_labels: Cluster assignment per document (parallel to all_features).
    :param strategy: Sampling strategy used.
    :param seed: Random seed used.
    """

    selected_paths: list[str]
    all_features: list[DocFeatures]
    cluster_labels: list[int] = field(default_factory=list)
    strategy: str = "diversity"
    seed: int = 42


class CorpusSampler:
    """Phase 1: extract NLP features, cluster for diversity, sample.

    :param corpus_root: Root directory of the corpus.
    :param cache_dir: Directory for feature caches (default: ``.dockg/cache``).
    :param n_clusters: Number of K-means clusters for diversity sampling.
    :param seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        corpus_root: Path,
        *,
        cache_dir: Path | None = None,
        n_clusters: int = 8,
        seed: int = 42,
    ) -> None:
        self.corpus_root = Path(corpus_root)
        self.cache_dir = cache_dir or (self.corpus_root / ".dockg" / "cache")
        self.n_clusters = n_clusters
        self.seed = seed

    def extract_features(self, paths: list[Path]) -> list[DocFeatures]:
        """Extract NLP features for all documents, using cache where valid.

        :param paths: Absolute paths to corpus text files.
        :return: Feature objects in the same order as *paths*.
        """
        features: list[DocFeatures] = []

        for idx, abs_path in enumerate(paths):
            try:
                text = abs_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                try:
                    text = abs_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    features.append(DocFeatures(
                        file_path=str(abs_path), file_hash="", temporal_index=idx
                    ))
                    continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            rel_path = self._rel_path(abs_path)

            # Check cache
            cached = self._load_cached(rel_path, content_hash)
            if cached is not None:
                cached.temporal_index = idx
                features.append(cached)
                continue

            # Extract features
            feat = self._extract_one(text, rel_path, content_hash, idx)
            features.append(feat)
            self._save_cache(feat)

        return features

    def sample(
        self,
        paths: list[Path],
        *,
        batch_size: int = 20,
        strategy: str = "diversity",
    ) -> SampleResult:
        """Select a representative sample from the corpus.

        :param paths: Absolute paths to corpus text files.
        :param batch_size: Number of documents to select.
        :param strategy: ``"diversity"`` (K-means), ``"random"``, or ``"temporal"``.
        :return: A :class:`SampleResult` with selected paths and metadata.
        """
        features = self.extract_features(paths)

        if batch_size >= len(paths):
            return SampleResult(
                selected_paths=[self._rel_path(p) for p in paths],
                all_features=features,
                cluster_labels=list(range(len(paths))),
                strategy=strategy,
                seed=self.seed,
            )

        if strategy == "diversity":
            selected, labels = self._diversity_sample(features, batch_size)
        elif strategy == "temporal":
            selected, labels = self._temporal_sample(features, batch_size)
        else:
            selected, labels = self._random_sample(features, batch_size)

        return SampleResult(
            selected_paths=selected,
            all_features=features,
            cluster_labels=labels,
            strategy=strategy,
            seed=self.seed,
        )

    # ------------------------------------------------------------------
    # Sampling strategies
    # ------------------------------------------------------------------

    def _diversity_sample(
        self, features: list[DocFeatures], batch_size: int
    ) -> tuple[list[str], list[int]]:
        """K-means clustering then sample from each cluster."""
        try:
            from sklearn.cluster import KMeans  # pylint: disable=import-outside-toplevel
            from sklearn.preprocessing import (  # pylint: disable=import-outside-toplevel
                StandardScaler,
            )
        except ImportError:
            logger.warning("scikit-learn not available; falling back to random sampling")
            return self._random_sample(features, batch_size)

        import numpy as np  # pylint: disable=import-outside-toplevel

        X = np.asarray([f.to_vector() for f in features], dtype="float32")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        actual_k = min(self.n_clusters, len(X))
        km = KMeans(n_clusters=actual_k, random_state=self.seed, n_init=10)
        labels = km.fit_predict(X_scaled).tolist()

        # Sample proportionally from each cluster
        rng = random.Random(self.seed)
        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(label, []).append(idx)

        selected_indices: list[int] = []
        per_cluster = max(1, batch_size // actual_k)

        for _label in sorted(clusters):
            members = clusters[_label]
            n_pick = min(per_cluster, len(members))
            selected_indices.extend(rng.sample(members, n_pick))

        # Fill remaining slots if needed
        remaining = batch_size - len(selected_indices)
        if remaining > 0:
            pool = [i for i in range(len(features)) if i not in set(selected_indices)]
            selected_indices.extend(rng.sample(pool, min(remaining, len(pool))))

        selected_indices = selected_indices[:batch_size]
        selected_paths = [features[i].file_path for i in selected_indices]

        return selected_paths, labels

    def _temporal_sample(
        self, features: list[DocFeatures], batch_size: int
    ) -> tuple[list[str], list[int]]:
        """Evenly spaced across temporal index."""
        n = len(features)
        indices = [round(i * (n - 1) / (batch_size - 1)) for i in range(batch_size)]
        indices = sorted(set(indices))[:batch_size]

        selected = [features[i].file_path for i in indices]
        labels = list(range(len(features)))
        return selected, labels

    def _random_sample(
        self, features: list[DocFeatures], batch_size: int
    ) -> tuple[list[str], list[int]]:
        """Simple random sample."""
        rng = random.Random(self.seed)
        indices = rng.sample(range(len(features)), min(batch_size, len(features)))
        selected = [features[i].file_path for i in indices]
        labels = list(range(len(features)))
        return selected, labels

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _extract_one(
        self, text: str, rel_path: str, content_hash: str, temporal_index: int
    ) -> DocFeatures:
        """Extract features from a single document."""
        tokens = _TOKEN_RE.findall(text)
        lower_tokens = [t.lower() for t in tokens]
        sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
        if len(sentences) <= 1:
            sentences = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        entities = _ENTITY_RE.findall(text)

        return DocFeatures(
            file_path=rel_path,
            file_hash=content_hash,
            n_tokens=len(tokens),
            n_sentences=max(1, len(sentences)),
            n_unique_words=len(set(lower_tokens)),
            n_entities=len(set(entities)),
            text_length=len(text),
            temporal_index=temporal_index,
        )

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _cache_path(self, rel_path: str, content_hash: str) -> Path:
        """Build per-file cache path."""
        slug = hashlib.sha256(rel_path.encode()).hexdigest()[:12]
        return self.cache_dir / f"{slug}_{content_hash[:8]}.pkl"

    def _load_cached(self, rel_path: str, content_hash: str) -> DocFeatures | None:
        """Load cached features if hash matches."""
        path = self._cache_path(rel_path, content_hash)
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                cached = pickle.load(f)  # noqa: S301
            if isinstance(cached, DocFeatures) and cached.file_hash == content_hash:
                return cached
        except (pickle.UnpicklingError, EOFError, AttributeError, OSError):
            path.unlink(missing_ok=True)
        return None

    def _save_cache(self, feat: DocFeatures) -> None:
        """Save features to pickle cache."""
        path = self._cache_path(feat.file_path, feat.file_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "wb") as f:
                pickle.dump(feat, f)
        except OSError:
            pass

    def _rel_path(self, abs_path: Path) -> str:
        """Return corpus-relative path."""
        try:
            return str(abs_path.relative_to(self.corpus_root)).replace("\\", "/")
        except ValueError:
            return str(abs_path).replace("\\", "/")
