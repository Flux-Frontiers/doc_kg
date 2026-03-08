"""Tests for semantic ranking behavior in kg.py."""

from doc_kg.kg import _semantic_rank_boost


def test_semantic_rank_boost_prioritizes_topic_entity_over_cooccur():
    node_id = "chunk:docs.md:0001"
    edges = [
        {"src": node_id, "rel": "CO_OCCURS_WITH", "dst": "entity:a"},
        {"src": node_id, "rel": "CO_OCCURS_WITH", "dst": "entity:b"},
        {"src": node_id, "rel": "CO_OCCURS_WITH", "dst": "entity:c"},
        {"src": node_id, "rel": "HAS_TOPIC", "dst": "topic:architecture"},
    ]

    score = _semantic_rank_boost(node_id, edges)

    # One HAS_TOPIC edge should outweigh several weak co-occurrence edges.
    assert score > 3 * 0.05


def test_semantic_rank_boost_counts_incident_edges_only():
    node_id = "entity:codekg"
    edges = [
        {"src": "chunk:a", "rel": "HAS_TOPIC", "dst": "topic:architecture"},
        {"src": node_id, "rel": "MENTIONS_ENTITY", "dst": "chunk:a"},
    ]

    score = _semantic_rank_boost(node_id, edges)
    assert score == 2.5
