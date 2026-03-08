"""Tests for semantic extraction helpers (topics/entities/ids)."""

from doc_kg.relations import (
    cooccur_pairs,
    extract_entities,
    stable_entity_id,
    stable_keyword_id,
    stable_topic_id,
)
from doc_kg.topics import TopicExtractor


def test_topic_extractor_classify_default_topics():
    extractor = TopicExtractor()
    matches = extractor.classify(
        "System architecture and API design improve performance."
    )
    assert matches
    assert any(m.topic == "architecture" for m in matches)


def test_topic_extractor_keywords_fallback():
    extractor = TopicExtractor()
    kws = extractor.extract_keywords("alpha beta alpha gamma")
    assert kws
    assert kws[0] == "alpha"


def test_extract_entities_detects_camelcase_and_acronyms():
    entities = extract_entities("DocKG integrates SQLite and LanceDB for analytics.")
    assert "DocKG" in entities
    assert "SQLite" in entities


def test_stable_ids_are_prefixed():
    assert stable_topic_id("Architecture") == "topic:architecture"
    assert stable_keyword_id("Query") == "keyword:query"
    assert stable_entity_id("DocKG").startswith("entity:")


def test_cooccur_pairs_dedup_and_sorted():
    pairs = cooccur_pairs(["b", "a", "a", "c"])
    assert pairs == [("a", "b"), ("a", "c"), ("b", "c")]
