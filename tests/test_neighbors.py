"""DocKG.neighbors() and GraphStore.edges_touching().

The same contract as ``kg_utils.pipeline.KGModule.neighbors``, so the fleet's
canonical ``neighbors`` MCP tool means the same on every server. Graph only:
built straight into the store, no vector index and no model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doc_kg import DocKG
from doc_kg.dockg import DocEdge, DocNode
from doc_kg.store import GraphStore


def _node(nid: str, kind: str) -> DocNode:
    return DocNode(
        id=nid,
        kind=kind,
        name=nid,
        title=None,
        file_path="a.md",
        char_start=0,
        char_end=1,
        heading_level=None,
        text=nid,
    )


@pytest.fixture
def kg(tmp_path: Path):
    """sec CONTAINS c0, c1; c0 NEXT c1; c0 HAS_TOPIC topic:t; c1 REFERENCES a ghost."""
    store = GraphStore(tmp_path / ".dockg" / "graph.sqlite")
    store.write(
        [
            _node("sec:a.md:s", "section"),
            _node("chunk:a.md:0000", "chunk"),
            _node("chunk:a.md:0001", "chunk"),
            _node("topic:t", "topic"),
        ],
        [
            DocEdge(src="sec:a.md:s", rel="CONTAINS", dst="chunk:a.md:0000"),
            DocEdge(src="sec:a.md:s", rel="CONTAINS", dst="chunk:a.md:0001"),
            DocEdge(src="chunk:a.md:0000", rel="NEXT", dst="chunk:a.md:0001"),
            DocEdge(src="chunk:a.md:0000", rel="HAS_TOPIC", dst="topic:t"),
            DocEdge(src="chunk:a.md:0001", rel="REFERENCES", dst="doc:ghost.md"),
        ],
        quiet=True,
    )
    store.close()
    kg = DocKG(tmp_path)
    yield kg
    kg.close()


def _pairs(result: dict) -> list[tuple[str, str, str]]:
    return [(e["src"], e["rel"], e["dst"]) for e in result["edges"]]


def test_both_directions_by_default(kg):
    result = kg.neighbors("chunk:a.md:0000")
    # Ordered by (rel, src, dst), so a capped result is deterministic.
    assert _pairs(result) == [
        ("sec:a.md:s", "CONTAINS", "chunk:a.md:0000"),
        ("chunk:a.md:0000", "HAS_TOPIC", "topic:t"),
        ("chunk:a.md:0000", "NEXT", "chunk:a.md:0001"),
    ]
    assert [n["id"] for n in result["nodes"]] == ["sec:a.md:s", "topic:t", "chunk:a.md:0001"]


def test_direction_and_rels_narrow_it(kg):
    assert _pairs(kg.neighbors("chunk:a.md:0000", direction="in")) == [
        ("sec:a.md:s", "CONTAINS", "chunk:a.md:0000")
    ]
    assert _pairs(kg.neighbors("sec:a.md:s", rels=["CONTAINS"], direction="out")) == [
        ("sec:a.md:s", "CONTAINS", "chunk:a.md:0000"),
        ("sec:a.md:s", "CONTAINS", "chunk:a.md:0001"),
    ]


def test_a_dangling_edge_is_kept_but_no_node_is_invented(kg):
    result = kg.neighbors("chunk:a.md:0001", rels=["REFERENCES"])
    assert _pairs(result) == [("chunk:a.md:0001", "REFERENCES", "doc:ghost.md")]
    assert result["nodes"] == []


def test_limit_caps_edges_deterministically(kg):
    assert len(kg.neighbors("chunk:a.md:0000", limit=2)["edges"]) == 2
    assert kg.neighbors("chunk:a.md:0000", limit=2) == kg.neighbors("chunk:a.md:0000", limit=2)


def test_unknown_node_is_none_like_node(kg):
    assert kg.node("nope") is None
    assert kg.neighbors("nope") is None


@pytest.mark.parametrize(
    ("node_id", "kwargs", "message"),
    [
        ("", {}, "node_id"),
        ("sec:a.md:s", {"direction": "sideways"}, "direction"),
        ("sec:a.md:s", {"limit": 0}, "limit"),
        ("sec:a.md:s", {"limit": 501}, "limit"),
        ("sec:a.md:s", {"limit": True}, "limit"),
    ],
)
def test_bad_arguments_name_the_parameter(kg, node_id, kwargs, message):
    with pytest.raises(ValueError, match=message):
        kg.neighbors(node_id, **kwargs)


def test_never_loads_the_embedding_model(kg, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("neighbors() loaded the embedding model")

    monkeypatch.setattr("doc_kg.kg.make_embedder", refuse)
    assert kg.neighbors("sec:a.md:s") is not None


def test_store_rejects_an_unknown_direction(kg):
    with pytest.raises(ValueError, match="direction"):
        kg.store.edges_touching("sec:a.md:s", direction="up")
