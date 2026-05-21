"""Tests for SIMILAR_TO edge discovery and max_degree pruning in SemanticIndex."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from doc_kg.index import SemanticIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(tmp_path):
    """Return a SemanticIndex with a fake embedder (no model loaded)."""
    embedder = MagicMock()
    idx = SemanticIndex.__new__(SemanticIndex)
    idx.embedder = embedder
    idx.lancedb_dir = tmp_path / "lancedb"
    idx.table_name = "nodes"
    idx.index_kinds = {"chunk"}
    return idx


def _make_store():
    """Return a mock GraphStore that records upserted edges."""
    store = MagicMock()
    store._upserted: list = []

    def _capture(edges):
        store._upserted.extend(edges)

    store._upsert_edges.side_effect = _capture
    return store


def _make_tbl(ann_results: dict[str, list[dict]]):
    """Return a mock LanceDB table whose search() returns per-query results."""
    tbl = MagicMock()

    call_count = [0]
    query_order: list[str] = list(ann_results.keys())

    def _search(vec):
        chain = MagicMock()
        idx_c = call_count[0] % len(query_order)
        src = query_order[idx_c]
        call_count[0] += 1
        chain.metric.return_value = chain
        chain.where.return_value = chain
        chain.limit.return_value = chain
        chain.to_list.return_value = ann_results[src]
        return chain

    tbl.search.side_effect = _search
    return tbl


# ---------------------------------------------------------------------------
# Unit tests for _discover_similar_edges
# ---------------------------------------------------------------------------


def _run_discovery(tmp_path, ann_results, chunk_ids, k=5, threshold=0.8, max_degree=0):
    idx = _make_index(tmp_path)
    store = _make_store()
    tbl = _make_tbl(ann_results)
    n = len(chunk_ids)
    chunk_vecs = np.zeros((n, 4), dtype=np.float32)

    added = idx._discover_similar_edges(
        store,
        tbl,
        chunk_ids,
        chunk_vecs,
        k=k,
        threshold=threshold,
        max_degree=max_degree,
        quiet=True,
    )
    return added, store._upserted


class TestDiscoverSimilarEdgesNoCapBasics:
    def test_empty_chunk_ids_returns_zero(self, tmp_path):
        idx = _make_index(tmp_path)
        store = _make_store()
        tbl = MagicMock()
        added = idx._discover_similar_edges(
            store,
            tbl,
            [],
            np.zeros((0, 4), dtype=np.float32),
            k=5,
            threshold=0.8,
            max_degree=0,
            quiet=True,
        )
        assert added == 0
        store._upsert_edges.assert_not_called()

    def test_self_hits_skipped(self, tmp_path):
        """ANN result containing the source node itself must be dropped."""
        chunk_ids = ["c:a"]
        ann_results = {
            "c:a": [{"id": "c:a", "_distance": 0.0}],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids)
        assert added == 0
        assert edges == []

    def test_below_threshold_skipped(self, tmp_path):
        chunk_ids = ["c:a", "c:b"]
        ann_results = {
            "c:a": [{"id": "c:b", "_distance": 0.5}],  # sim=0.5 < 0.8
            "c:b": [{"id": "c:a", "_distance": 0.5}],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.8)
        assert added == 0

    def test_edge_written_above_threshold(self, tmp_path):
        chunk_ids = ["c:a", "c:b"]
        # Only one direction returns a hit to avoid duplicate canonical writes.
        ann_results = {
            "c:a": [{"id": "c:b", "_distance": 0.05}],  # sim=0.95
            "c:b": [],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.8)
        assert added == 1
        assert edges[0].rel == "SIMILAR_TO"

    def test_canonical_direction(self, tmp_path):
        """Edge src < dst lexicographically regardless of query order."""
        chunk_ids = ["c:z", "c:a"]
        ann_results = {
            "c:z": [{"id": "c:a", "_distance": 0.05}],
            "c:a": [{"id": "c:z", "_distance": 0.05}],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5)
        # Both A→Z and Z→A hits canonicalize to (c:a, c:z)
        srcs = {e.src for e in edges}
        dsts = {e.dst for e in edges}
        assert srcs == {"c:a"}
        assert dsts == {"c:z"}

    def test_similarity_stored_in_evidence(self, tmp_path):
        chunk_ids = ["c:a", "c:b"]
        ann_results = {
            "c:a": [{"id": "c:b", "_distance": 0.1}],  # sim=0.9
            "c:b": [],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5)
        assert added == 1
        assert edges[0].evidence["similarity"] == pytest.approx(0.9, abs=0.001)


# ---------------------------------------------------------------------------
# max_degree pruning tests
# ---------------------------------------------------------------------------


class TestMaxDegreePruning:
    def _make_star_scenario(self):
        """Hub 'c:hub' appears as a neighbor for all spokes at high similarity."""
        chunk_ids = ["c:hub", "c:s1", "c:s2", "c:s3", "c:s4"]
        # Each spoke sees hub as its nearest neighbor at sim ~0.99
        # Hub sees all spokes at sim ~0.99
        ann_results = {
            "c:hub": [
                {"id": "c:s1", "_distance": 0.01},
                {"id": "c:s2", "_distance": 0.01},
                {"id": "c:s3", "_distance": 0.01},
                {"id": "c:s4", "_distance": 0.01},
            ],
            "c:s1": [{"id": "c:hub", "_distance": 0.01}],
            "c:s2": [{"id": "c:hub", "_distance": 0.01}],
            "c:s3": [{"id": "c:hub", "_distance": 0.01}],
            "c:s4": [{"id": "c:hub", "_distance": 0.01}],
        }
        return chunk_ids, ann_results

    def test_max_degree_zero_is_unlimited(self, tmp_path):
        chunk_ids, ann_results = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5, max_degree=0)
        # Both hub→spoke and spoke→hub hits produce the same canonical pair;
        # SQLite deduplicates on upsert. Check unique (src, dst) pairs instead.
        unique_pairs = {(e.src, e.dst) for e in edges}
        assert len(unique_pairs) == 4  # all 4 spoke-hub pairs

    def test_max_degree_cap_enforced(self, tmp_path):
        chunk_ids, ann_results = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5, max_degree=2)
        # Hub degree must not exceed 2
        hub_degree = sum(1 for e in edges if e.src == "c:hub" or e.dst == "c:hub")
        assert hub_degree <= 2

    def test_max_degree_one(self, tmp_path):
        chunk_ids, ann_results = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5, max_degree=1)
        # No node may appear more than once
        from collections import Counter

        degree = Counter()
        for e in edges:
            degree[e.src] += 1
            degree[e.dst] += 1
        assert max(degree.values(), default=0) <= 1

    def test_max_degree_prefers_higher_similarity(self, tmp_path):
        """With max_degree=1, the strongest edge per node is kept."""
        chunk_ids = ["c:a", "c:b", "c:c"]
        # c:a sees c:b at 0.99 and c:c at 0.85; with max_degree=1 should keep c:b
        ann_results = {
            "c:a": [
                {"id": "c:b", "_distance": 0.01},  # sim=0.99
                {"id": "c:c", "_distance": 0.15},  # sim=0.85
            ],
            "c:b": [{"id": "c:a", "_distance": 0.01}],
            "c:c": [{"id": "c:a", "_distance": 0.15}],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.5, max_degree=1)
        # The kept edge should be the highest-sim pair (c:a, c:b)
        kept_pairs = {(e.src, e.dst) for e in edges}
        assert ("c:a", "c:b") in kept_pairs

    def test_no_edges_when_threshold_filters_all(self, tmp_path):
        chunk_ids = ["c:a", "c:b"]
        ann_results = {
            "c:a": [{"id": "c:b", "_distance": 0.8}],  # sim=0.2 < 0.9
            "c:b": [{"id": "c:a", "_distance": 0.8}],
        }
        added, edges = _run_discovery(tmp_path, ann_results, chunk_ids, threshold=0.9, max_degree=3)
        assert added == 0
        assert edges == []

    def test_max_degree_all_nodes_respected(self, tmp_path):
        """Every node's degree in the result must not exceed max_degree."""
        chunk_ids = [f"c:{i}" for i in range(6)]
        # Dense fully-connected scenario: everyone is similar to everyone
        ann_results = {}
        for cid in chunk_ids:
            neighbors = [{"id": other, "_distance": 0.02} for other in chunk_ids if other != cid]
            ann_results[cid] = neighbors

        cap = 2
        added, edges = _run_discovery(
            tmp_path, ann_results, chunk_ids, threshold=0.5, max_degree=cap
        )
        from collections import Counter

        degree = Counter()
        for e in edges:
            degree[e.src] += 1
            degree[e.dst] += 1
        for node, deg in degree.items():
            assert deg <= cap, f"{node} has degree {deg} > cap {cap}"


# ---------------------------------------------------------------------------
# build_from_cache dispatch tests
# ---------------------------------------------------------------------------


class TestBuildFromCacheDispatch:
    """Verify build_from_cache forwards all args to the correct internal path."""

    def test_jsonl_path_forwards_similar_max_degree(self, tmp_path):
        """similar_max_degree must reach _build_from_jsonl_cache — missing it raises TypeError."""
        idx = _make_index(tmp_path)
        store = _make_store()
        cache = tmp_path / "embeddings.jsonl"
        cache.touch()

        sentinel = {"indexed_rows": 0, "dim": 0, "similar_edges_added": 0}
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            idx, "_build_from_jsonl_cache", return_value=sentinel
        ) as mock_fn:
            idx.build_from_cache(store, cache, quiet=True, similar_max_degree=3)
            _, kwargs = mock_fn.call_args
            assert kwargs["similar_max_degree"] == 3
