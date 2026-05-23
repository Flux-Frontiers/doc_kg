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


# ---------------------------------------------------------------------------
# Unit tests for _discover_similar_edges
# ---------------------------------------------------------------------------


def _run_discovery(tmp_path, chunk_ids, chunk_vecs, k=5, threshold=0.8, max_degree=0):
    """Drive _discover_similar_edges with real vectors; tbl arg is accepted but unused."""
    idx = _make_index(tmp_path)
    store = _make_store()
    tbl = MagicMock()

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
        """A single chunk must never produce a self-edge."""
        chunk_ids = ["c:a"]
        chunk_vecs = np.array([[1, 0, 0, 0, 0, 0]], dtype=np.float32)
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs)
        assert added == 0
        assert edges == []

    def test_below_threshold_skipped(self, tmp_path):
        # Orthogonal unit vectors → cosine sim = 0 < 0.8 threshold.
        chunk_ids = ["c:a", "c:b"]
        chunk_vecs = np.array([[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]], dtype=np.float32)
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.8)
        assert added == 0

    def test_edge_written_above_threshold(self, tmp_path):
        # Identical unit vectors → cosine sim = 1.0 > 0.8.
        # Both directions produce the same canonical pair; assert on unique pairs.
        chunk_ids = ["c:a", "c:b"]
        chunk_vecs = np.array([[1, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0]], dtype=np.float32)
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.8)
        unique_pairs = {(e.src, e.dst) for e in edges}
        assert unique_pairs == {("c:a", "c:b")}
        assert edges[0].rel == "SIMILAR_TO"

    def test_canonical_direction(self, tmp_path):
        """Edge src < dst lexicographically regardless of chunk order."""
        chunk_ids = ["c:z", "c:a"]
        chunk_vecs = np.array([[1, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0]], dtype=np.float32)
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5)
        srcs = {e.src for e in edges}
        dsts = {e.dst for e in edges}
        assert srcs == {"c:a"}
        assert dsts == {"c:z"}

    def test_similarity_stored_in_evidence(self, tmp_path):
        # v1=[1,0,...], v2=[0.9, sqrt(0.19), 0,...] → dot product = 0.9 exactly.
        chunk_ids = ["c:a", "c:b"]
        chunk_vecs = np.array(
            [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.9, float(np.sqrt(0.19)), 0.0, 0.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5)
        unique_pairs = {(e.src, e.dst) for e in edges}
        assert unique_pairs == {("c:a", "c:b")}
        assert edges[0].evidence["similarity"] == pytest.approx(0.9, abs=0.001)


# ---------------------------------------------------------------------------
# max_degree pruning tests
# ---------------------------------------------------------------------------


class TestMaxDegreePruning:
    def _make_star_scenario(self):
        """Hub + 4 spokes: hub-spoke sim=0.6, spoke-spoke sim=0.36 (below threshold=0.5).

        dim=6 gives each spoke a unique orthogonal component so spokes are far
        from each other while remaining close to the hub.
        """
        chunk_ids = ["c:hub", "c:s1", "c:s2", "c:s3", "c:s4"]
        chunk_vecs = np.array(
            [
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # hub  — norm=1
                [0.6, 0.8, 0.0, 0.0, 0.0, 0.0],  # s1   — sim(hub)=0.6, norm=1
                [0.6, 0.0, 0.8, 0.0, 0.0, 0.0],  # s2   — sim(hub)=0.6, norm=1
                [0.6, 0.0, 0.0, 0.8, 0.0, 0.0],  # s3   — sim(hub)=0.6, norm=1
                [0.6, 0.0, 0.0, 0.0, 0.8, 0.0],  # s4   — sim(hub)=0.6, norm=1
            ],
            dtype=np.float32,
        )
        return chunk_ids, chunk_vecs

    def test_max_degree_zero_is_unlimited(self, tmp_path):
        chunk_ids, chunk_vecs = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5, max_degree=0)
        unique_pairs = {(e.src, e.dst) for e in edges}
        assert len(unique_pairs) == 4  # all 4 hub-spoke pairs; spoke-spoke sim=0.36 < 0.5

    def test_max_degree_cap_enforced(self, tmp_path):
        chunk_ids, chunk_vecs = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5, max_degree=2)
        hub_degree = sum(1 for e in edges if e.src == "c:hub" or e.dst == "c:hub")
        assert hub_degree <= 2

    def test_max_degree_one(self, tmp_path):
        chunk_ids, chunk_vecs = self._make_star_scenario()
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5, max_degree=1)
        from collections import Counter

        degree = Counter()
        for e in edges:
            degree[e.src] += 1
            degree[e.dst] += 1
        assert max(degree.values(), default=0) <= 1

    def test_max_degree_prefers_higher_similarity(self, tmp_path):
        """With max_degree=1, the strongest edge per node is kept."""
        # a-b sim=0.99, a-c sim=0.85; greedy picks (a,b) first, leaving both a and b full.
        chunk_ids = ["c:a", "c:b", "c:c"]
        b_comp = float(np.sqrt(1.0 - 0.99**2))
        c_comp = float(np.sqrt(1.0 - 0.85**2))
        chunk_vecs = np.array(
            [
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.99, b_comp, 0.0, 0.0, 0.0, 0.0],
                [0.85, c_comp, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.5, max_degree=1)
        kept_pairs = {(e.src, e.dst) for e in edges}
        assert ("c:a", "c:b") in kept_pairs

    def test_no_edges_when_threshold_filters_all(self, tmp_path):
        # Orthogonal unit vectors → cosine sim = 0 < 0.9 threshold.
        chunk_ids = ["c:a", "c:b"]
        chunk_vecs = np.array([[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]], dtype=np.float32)
        added, edges = _run_discovery(tmp_path, chunk_ids, chunk_vecs, threshold=0.9, max_degree=3)
        assert added == 0
        assert edges == []

    def test_max_degree_all_nodes_respected(self, tmp_path):
        """Every node's degree in the result must not exceed max_degree."""
        chunk_ids = [f"c:{i}" for i in range(6)]
        # All identical unit vectors → all 15 pairs have sim=1.0 > threshold=0.5.
        chunk_vecs = np.tile(np.array([[1, 0, 0, 0, 0, 0]], dtype=np.float32), (6, 1))

        cap = 2
        added, edges = _run_discovery(
            tmp_path, chunk_ids, chunk_vecs, threshold=0.5, max_degree=cap
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
