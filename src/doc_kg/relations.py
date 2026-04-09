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


_VALUE_PATTERNS: list[re.Pattern] = [
    # Percentages: "10%", "5.5 %"
    re.compile(r"\b\d+(?:\.\d+)?\s*%"),
    # Currency amounts: "$5", "£20", "€100", "$1,200"
    re.compile(r"[$£€¥]\d[\d,]*(?:\.\d+)?"),
    # Color phrases: "lighter shade of gray", "deep blue", "matte black", etc.
    re.compile(
        r"\b(?:lighter|darker|light|dark|deep|pale|bright|matte|glossy|"
        r"shiny|vivid|bold|soft|warm|cool)\s+"
        r"(?:shade\s+of\s+)?(?:red|orange|yellow|green|blue|purple|pink|"
        r"brown|gray|grey|black|white|beige|cream|ivory|gold|silver|teal|"
        r"coral|lavender|navy|maroon|olive|cyan|magenta|indigo|violet|tan|khaki)\b",
        re.IGNORECASE,
    ),
    # Plain color words that appear as standalone descriptors
    re.compile(
        r"\b(?:red|orange|yellow|green|blue|purple|pink|brown|gray|grey|"
        r"black|white|beige|cream|ivory|gold|silver|teal|coral|lavender|"
        r"navy|maroon|olive|cyan|magenta|indigo|violet|tan|khaki)\b",
        re.IGNORECASE,
    ),
    # Lowercase occupational role phrases: "marketing specialist", "software engineer", etc.
    re.compile(
        r"\b(?:marketing|sales|software|data|product|project|financial|"
        r"senior|junior|lead|chief|head|staff|assistant|associate|principal)"
        r"\s+(?:specialist|engineer|manager|analyst|director|consultant|"
        r"coordinator|developer|designer|officer|scientist|advisor|executive|"
        r"architect|strategist)\b",
        re.IGNORECASE,
    ),
]


def extract_entities(text: str, *, max_entities: int = 8) -> list[str]:
    """Extract likely named entities from capitalized spans and value patterns.

    Captures titlecase proper nouns plus numeric values (percentages, currency),
    color phrases, and lowercase occupational role phrases that are semantically
    important but missed by capitalization-only heuristics.

    :param text: Chunk text.
    :param max_entities: Max entities returned.
    :return: Ordered de-duplicated entity names.
    """
    # Multi-word titlecase entities, acronyms, and CamelCase identifiers.
    cap_pattern = re.compile(
        r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}"
        r"|[A-Z]{2,}[A-Z0-9]*"
        r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
        r"|[A-Z]{2,}[a-z][A-Za-z0-9]*)\b"
    )
    found: list[str] = [m.group(0).strip() for m in cap_pattern.finditer(text)]

    # Value and phrase patterns (order matters: more specific first)
    for pat in _VALUE_PATTERNS:
        for m in pat.finditer(text):
            found.append(m.group(0).strip())

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
