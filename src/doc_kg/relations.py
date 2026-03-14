#!/usr/bin/env python3
"""
relations.py

Entity and relationship extraction utilities for DocKG.

Focuses on deterministic, lightweight extraction so corpus parsing stays fast
while still emitting richer graph structure.
"""

from __future__ import annotations

import hashlib
import itertools
import re

_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def stable_topic_id(topic: str) -> str:
    """Return stable topic node ID.

    :param topic: Topic label.
    :return: Topic node id.
    """
    slug = _slug(topic)
    return f"topic:{slug}"


def stable_entity_id(entity_name: str) -> str:
    """Return stable entity node ID.

    :param entity_name: Entity label.
    :return: Entity node id.
    """
    slug = _slug(entity_name)
    if len(slug) > 60:
        digest = hashlib.sha1(entity_name.encode("utf-8")).hexdigest()[:12]
        slug = f"{slug[:40]}-{digest}"
    return f"entity:{slug}"


def stable_keyword_id(keyword: str) -> str:
    """Return stable keyword node ID.

    :param keyword: Keyword token.
    :return: Keyword node id.
    """
    return f"keyword:{_slug(keyword)}"


def extract_entities(text: str, *, max_entities: int = 8) -> list[str]:
    """Extract likely named entities from capitalized spans.

    This intentionally avoids heavy NLP dependencies while capturing practical
    project entities such as class names, library names, org names, and tools.

    :param text: Chunk text.
    :param max_entities: Max entities returned.
    :return: Ordered de-duplicated entity names.
    """
    # Multi-word titlecase entities, acronyms, and CamelCase identifiers.
    pattern = re.compile(
        r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}"
        r"|[A-Z]{2,}[A-Z0-9]*"
        r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
        r"|[A-Z]{2,}[a-z][A-Za-z0-9]*)\b"
    )
    found = [m.group(0).strip() for m in pattern.finditer(text)]

    entities: list[str] = []
    seen: set[str] = set()
    for raw in found:
        norm = raw.strip()
        if not norm:
            continue
        if norm.lower() in _TITLE_STOPWORDS:
            continue
        if len(norm) < 2:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(norm)
        if len(entities) >= max_entities:
            break

    return entities


def cooccur_pairs(items: list[str]) -> list[tuple[str, str]]:
    """Return deterministic pairwise co-occurrence edges.

    :param items: Item IDs participating in co-occurrence.
    :return: Sorted unique tuple pairs.
    """
    uniq = sorted(set(items))
    return list(itertools.combinations(uniq, 2))


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "unknown"
