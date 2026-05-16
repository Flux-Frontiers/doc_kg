#!/usr/bin/env python3
"""
topics.py

Topic extraction utilities for DocKG.

Implements a lightweight hybrid topic detector inspired by personal_agent's
DiaryTransformer approach:
- supervised keyword/topic mapping (from built-ins or user topic file)
- confidence scoring
- fallback keyword extraction for sparse text
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pylint: disable=broad-exception-caught  # pragma: no cover - optional dependency at runtime
    yaml = None  # type: ignore[assignment]  # pylint: disable=invalid-name


_DEFAULT_TOPICS: dict[str, list[str]] = {
    # --- Technology ---
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "system",
        "module",
        "api",
        "interface",
        "component",
    ],
    "implementation": [
        "implement",
        "code",
        "function",
        "class",
        "method",
        "logic",
        "algorithm",
        "routine",
    ],
    "testing": [
        "test",
        "pytest",
        "coverage",
        "assert",
        "fixture",
        "failing",
        "unit",
        "integration",
    ],
    "deployment": [
        "deploy",
        "release",
        "build",
        "ci",
        "cd",
        "pipeline",
        "container",
        "infrastructure",
    ],
    "data": ["data", "database", "schema", "table", "index", "query", "dataset", "record"],
    "documentation": [
        "docs",
        "readme",
        "guide",
        "reference",
        "example",
        "tutorial",
        "manual",
        "specification",
    ],
    "security": [
        "auth",
        "security",
        "token",
        "permission",
        "secret",
        "vulnerability",
        "encryption",
        "firewall",
    ],
    "performance": [
        "performance",
        "latency",
        "speed",
        "optimize",
        "cache",
        "throughput",
        "benchmark",
        "profiling",
    ],
    # --- Humanities ---
    "history": [
        "history",
        "historical",
        "ancient",
        "medieval",
        "century",
        "era",
        "civilization",
        "empire",
        "dynasty",
        "war",
        "revolution",
        "chronicle",
        "antiquity",
        "epoch",
    ],
    "philosophy": [
        "philosophy",
        "metaphysics",
        "epistemology",
        "ethics",
        "logic",
        "ontology",
        "consciousness",
        "reason",
        "truth",
        "existence",
        "dialectic",
        "phenomenology",
    ],
    "religion": [
        "religion",
        "spiritual",
        "sacred",
        "divine",
        "god",
        "faith",
        "prayer",
        "scripture",
        "theology",
        "ritual",
        "worship",
        "soul",
        "church",
        "temple",
        "mosque",
        "prophecy",
    ],
    "literature": [
        "poem",
        "poetry",
        "novel",
        "narrative",
        "fiction",
        "prose",
        "verse",
        "author",
        "character",
        "plot",
        "metaphor",
        "allegory",
        "genre",
        "tragedy",
        "comedy",
    ],
    "linguistics": [
        "language",
        "grammar",
        "syntax",
        "semantics",
        "phonology",
        "morphology",
        "dialect",
        "etymology",
        "translation",
        "corpus",
        "lexicon",
        "discourse",
    ],
    # --- Sciences ---
    "science": [
        "hypothesis",
        "experiment",
        "observation",
        "theory",
        "physics",
        "chemistry",
        "biology",
        "research",
        "laboratory",
        "empirical",
        "molecular",
        "quantum",
    ],
    "mathematics": [
        "theorem",
        "proof",
        "equation",
        "algebra",
        "calculus",
        "geometry",
        "topology",
        "probability",
        "statistics",
        "matrix",
        "function",
        "variable",
        "integral",
    ],
    "medicine": [
        "disease",
        "diagnosis",
        "treatment",
        "patient",
        "clinical",
        "symptom",
        "therapy",
        "pharmaceutical",
        "surgery",
        "anatomy",
        "pathology",
        "prognosis",
        "dosage",
    ],
    "environment": [
        "ecology",
        "climate",
        "biodiversity",
        "species",
        "habitat",
        "conservation",
        "ecosystem",
        "pollution",
        "renewable",
        "atmosphere",
        "geology",
        "ocean",
    ],
    # --- Social Sciences ---
    "politics": [
        "government",
        "democracy",
        "policy",
        "election",
        "parliament",
        "legislation",
        "sovereignty",
        "constitution",
        "party",
        "diplomacy",
        "ideology",
        "republic",
    ],
    "economics": [
        "economy",
        "market",
        "trade",
        "finance",
        "investment",
        "inflation",
        "capital",
        "supply",
        "demand",
        "fiscal",
        "monetary",
        "gdp",
        "commodity",
        "banking",
    ],
    "law": [
        "law",
        "legal",
        "statute",
        "court",
        "jurisdiction",
        "contract",
        "plaintiff",
        "defendant",
        "verdict",
        "legislation",
        "rights",
        "constitution",
        "regulation",
    ],
    "education": [
        "learning",
        "teaching",
        "curriculum",
        "student",
        "school",
        "university",
        "pedagogy",
        "assessment",
        "literacy",
        "scholarship",
        "academic",
        "instruction",
    ],
    "psychology": [
        "cognition",
        "behavior",
        "emotion",
        "consciousness",
        "memory",
        "perception",
        "motivation",
        "anxiety",
        "personality",
        "therapy",
        "neuroscience",
        "trauma",
    ],
    # --- Arts & Culture ---
    "art": [
        "painting",
        "sculpture",
        "visual",
        "aesthetic",
        "canvas",
        "artist",
        "gallery",
        "composition",
        "color",
        "style",
        "renaissance",
        "modernism",
        "portrait",
    ],
    "music": [
        "melody",
        "harmony",
        "rhythm",
        "chord",
        "symphony",
        "composition",
        "instrument",
        "tempo",
        "pitch",
        "genre",
        "concert",
        "notation",
        "orchestra",
        "vocal",
    ],
    # --- Biography & Ethics ---
    "biography": [
        "born",
        "life",
        "memoir",
        "autobiography",
        "childhood",
        "career",
        "death",
        "legacy",
        "portrait",
        "family",
        "journey",
        "achievement",
        "influence",
    ],
    "ethics": [
        "moral",
        "virtue",
        "justice",
        "duty",
        "rights",
        "good",
        "evil",
        "principle",
        "conscience",
        "integrity",
        "fairness",
        "obligation",
        "harm",
        "dignity",
    ],
    # --- Geography & Narrative ---
    "geography": [
        "region",
        "territory",
        "continent",
        "nation",
        "border",
        "landscape",
        "topography",
        "latitude",
        "longitude",
        "cartography",
        "urban",
        "rural",
        "migration",
    ],
    "narrative": [
        "story",
        "tale",
        "account",
        "episode",
        "journey",
        "adventure",
        "quest",
        "protagonist",
        "conflict",
        "resolution",
        "setting",
        "scene",
        "chapter",
    ],
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}


@dataclass(frozen=True)
class TopicMatch:
    """A single topic classification result.

    :param topic: Canonical topic name.
    :param score: Confidence score in [0, 1].
    :param matched_terms: Terms that contributed to this score.
    """

    topic: str
    score: float
    matched_terms: list[str]


class TopicExtractor:
    """Hybrid topic detector using keyword catalogs and confidence scoring.

    :param topics_file: Optional YAML/JSON file defining topics->keywords.
                        Expected format:
                        ``{ "topic": ["keyword1", "keyword2"] }``
                        or ``{ "topics": { ... } }``.
    """

    def __init__(self, topics_file: str | None = None) -> None:
        self.topic_map = self._load_topic_map(topics_file)
        self._kmeans: Any = None
        self._cluster_labels: list[str] = []

    def classify(
        self,
        text: str,
        *,
        threshold: float = 0.2,
        top_k: int = 3,
    ) -> list[TopicMatch]:
        """Return high-confidence topics for *text*.

        :param text: Raw chunk text.
        :param threshold: Minimum confidence to keep a topic.
        :param top_k: Max topics returned.
        :return: Topic matches ordered by confidence descending.
        """
        tokens = _tokenize(text)
        if not tokens:
            return []

        scores: list[TopicMatch] = []
        unique_tokens = set(tokens)
        text_lower = text.lower()

        for topic, keywords in self.topic_map.items():
            kw = [k.lower() for k in keywords if k.strip()]
            if not kw:
                continue
            # Single-word keywords: fast set lookup.
            # Multi-word keywords: substring search on lowercased text.
            matched = sorted(
                k
                for k in kw
                if (" " in k and k in text_lower) or (" " not in k and k in unique_tokens)
            )
            if not matched:
                continue
            # Confidence balances topic coverage and text density.
            coverage = len(matched) / max(1, len(set(kw)))
            density = len(matched) / max(1, min(12, len(unique_tokens)))
            score = min(1.0, (coverage * 0.75) + (density * 0.25))
            if score >= threshold:
                scores.append(TopicMatch(topic=topic, score=round(score, 4), matched_terms=matched))

        scores.sort(key=lambda x: x.score, reverse=True)
        if scores:
            return scores[:top_k]

        # Fallback: no configured topics matched; synthesize pseudo-topic from keywords.
        fallback = self.extract_keywords(text, max_keywords=2)
        if fallback:
            pseudo = "_".join(fallback)
            return [TopicMatch(topic=f"topic:{pseudo}", score=0.2, matched_terms=fallback)]
        return []

    def extract_keywords(self, text: str, *, max_keywords: int = 5) -> list[str]:
        """Extract top lexical keywords from *text*.

        :param text: Raw text.
        :param max_keywords: Maximum keywords to return.
        :return: Lowercased keywords sorted by frequency then alphabetically.
        """
        tokens = [t for t in _tokenize(text) if t not in _STOPWORDS]
        if not tokens:
            return []

        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1

        ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        return [k for k, _ in ordered[:max_keywords]]

    def _load_topic_map(self, topics_file: str | None) -> dict[str, list[str]]:
        if not topics_file:
            return _DEFAULT_TOPICS

        path = Path(topics_file)
        if not path.exists():
            raise FileNotFoundError(f"Topics file not found: {topics_file}")

        raw: dict
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()

        if suffix == ".json":
            raw = json.loads(text)
        elif suffix in (".yml", ".yaml"):
            if yaml is None:
                raise RuntimeError(
                    "PyYAML is required for YAML topic files. Install `pyyaml` or use JSON."
                )
            parsed = yaml.safe_load(text)
            if not isinstance(parsed, dict):
                raise ValueError("Invalid YAML topics format: expected mapping")
            raw = parsed
        else:
            raise ValueError("Unsupported topics file format; use .json, .yml, or .yaml")

        if "topics" in raw and isinstance(raw["topics"], dict):
            raw = raw["topics"]

        topic_map: dict[str, list[str]] = {}
        for topic, terms in raw.items():
            if isinstance(terms, list):
                topic_map[str(topic).strip().lower()] = [str(t).strip().lower() for t in terms]
            elif (
                isinstance(terms, dict)
                and "keywords" in terms
                and isinstance(terms["keywords"], list)
            ):
                topic_map[str(topic).strip().lower()] = [
                    str(t).strip().lower() for t in terms["keywords"]
                ]

        if not topic_map:
            raise ValueError("No valid topics found in topics file")
        return topic_map

    # ------------------------------------------------------------------
    # Unsupervised K-means fallback (Phase 3 hybrid classification)
    # ------------------------------------------------------------------

    def fit_clusters(
        self,
        embeddings: list[list[float]],
        *,
        n_clusters: int = 8,
        labels: list[str] | None = None,
    ) -> None:
        """Fit K-means on a set of chunk embeddings for unsupervised fallback.

        Must be called before ``classify_hybrid()`` can use the unsupervised
        path.  Requires ``scikit-learn``.

        :param embeddings: List of float32 vectors (one per chunk).
        :param n_clusters: Number of clusters.
        :param labels: Optional human-readable cluster labels (length == n_clusters).
        """
        try:
            from sklearn.cluster import KMeans  # pylint: disable=import-outside-toplevel
            from sklearn.preprocessing import (  # pylint: disable=import-outside-toplevel
                normalize,
            )
        except ImportError as exc:
            raise ImportError(
                "scikit-learn is required for unsupervised topic clustering. "
                "Install it with: pip install scikit-learn"
            ) from exc

        import numpy as np  # pylint: disable=import-outside-toplevel

        embeddings_arr = np.asarray(embeddings, dtype="float32")
        embeddings_arr = normalize(embeddings_arr)

        actual_k = min(n_clusters, len(embeddings_arr))
        self._kmeans = KMeans(n_clusters=actual_k, random_state=42, n_init=10)
        self._kmeans.fit(embeddings_arr)

        if labels and len(labels) == actual_k:
            self._cluster_labels = labels
        else:
            self._cluster_labels = [f"cluster_{i}" for i in range(actual_k)]

    def classify_hybrid(
        self,
        text: str,
        embedding: list[float] | None = None,
        *,
        supervised_threshold: float = 0.3,
        top_k: int = 3,
    ) -> tuple[list[TopicMatch], str]:
        """Hybrid classification: supervised first, unsupervised fallback.

        Returns the topic matches and a method tag indicating which classifier
        produced the result.

        :param text: Chunk text.
        :param embedding: Pre-computed embedding vector (required for unsupervised path).
        :param supervised_threshold: Minimum confidence to accept supervised result.
        :param top_k: Max topics returned.
        :return: ``(matches, method)`` where method is ``"supervised"``,
                 ``"unsupervised"``, or ``"fallback"``.
        """
        # Try supervised first
        supervised = self.classify(text, threshold=supervised_threshold, top_k=top_k)
        if supervised and supervised[0].score >= supervised_threshold:
            return supervised, "supervised"

        # Try unsupervised if K-means is fitted and we have an embedding
        if embedding is not None and hasattr(self, "_kmeans") and self._kmeans is not None:
            try:
                return self._classify_unsupervised(embedding), "unsupervised"
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        # Final fallback: return whatever supervised gave us (even low confidence)
        if supervised:
            return supervised, "fallback"

        return [], "fallback"

    def _classify_unsupervised(self, embedding: list[float]) -> list[TopicMatch]:
        """Assign a cluster-based topic using the fitted K-means model.

        :param embedding: Float32 embedding vector.
        :return: Single-element list with the cluster topic.
        """
        import numpy as np  # pylint: disable=import-outside-toplevel
        from sklearn.preprocessing import (  # pylint: disable=import-outside-toplevel
            normalize,
        )

        vec = normalize(np.asarray([embedding], dtype="float32"))
        cluster_idx = int(self._kmeans.predict(vec)[0])

        # Compute confidence from distance to centroid (closer = higher)
        centroid = self._kmeans.cluster_centers_[cluster_idx]
        dist = float(np.linalg.norm(vec[0] - centroid))
        # Map distance to [0, 1] confidence (inverse, capped)
        confidence = max(0.1, min(1.0, 1.0 / (1.0 + dist)))

        label = self._cluster_labels[cluster_idx]
        return [
            TopicMatch(
                topic=f"cluster:{label}",
                score=round(confidence, 4),
                matched_terms=[],
            )
        ]


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in re.finditer(r"[A-Za-z][A-Za-z0-9_\-]{1,30}", text)]
