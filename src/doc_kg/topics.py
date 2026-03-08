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

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency at runtime
    yaml = None


_DEFAULT_TOPICS: dict[str, list[str]] = {
    "architecture": ["architecture", "design", "pattern", "system", "module", "api"],
    "implementation": ["implement", "code", "function", "class", "method", "logic"],
    "testing": ["test", "pytest", "coverage", "assert", "fixture", "failing"],
    "deployment": ["deploy", "release", "build", "ci", "cd", "pipeline"],
    "data": ["data", "database", "schema", "table", "index", "query"],
    "documentation": ["docs", "readme", "guide", "reference", "example", "tutorial"],
    "security": ["auth", "security", "token", "permission", "secret", "vulnerability"],
    "performance": [
        "performance",
        "latency",
        "speed",
        "optimize",
        "cache",
        "throughput",
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

        for topic, keywords in self.topic_map.items():
            kw = [k.lower() for k in keywords if k.strip()]
            if not kw:
                continue
            matched = sorted([k for k in kw if k in unique_tokens])
            if not matched:
                continue
            # Confidence balances topic coverage and text density.
            coverage = len(matched) / max(1, len(set(kw)))
            density = len(matched) / max(1, min(12, len(unique_tokens)))
            score = min(1.0, (coverage * 0.75) + (density * 0.25))
            if score >= threshold:
                scores.append(
                    TopicMatch(
                        topic=topic, score=round(score, 4), matched_terms=matched
                    )
                )

        scores.sort(key=lambda x: x.score, reverse=True)
        if scores:
            return scores[:top_k]

        # Fallback: no configured topics matched; synthesize pseudo-topic from keywords.
        fallback = self.extract_keywords(text, max_keywords=2)
        if fallback:
            pseudo = "_".join(fallback)
            return [
                TopicMatch(topic=f"topic:{pseudo}", score=0.2, matched_terms=fallback)
            ]
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
            raise ValueError(
                "Unsupported topics file format; use .json, .yml, or .yaml"
            )

        if "topics" in raw and isinstance(raw["topics"], dict):
            raw = raw["topics"]

        topic_map: dict[str, list[str]] = {}
        for topic, terms in raw.items():
            if isinstance(terms, list):
                topic_map[str(topic).strip().lower()] = [
                    str(t).strip().lower() for t in terms
                ]
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


def _tokenize(text: str) -> list[str]:
    return [
        m.group(0).lower() for m in re.finditer(r"[A-Za-z][A-Za-z0-9_\-]{1,30}", text)
    ]
