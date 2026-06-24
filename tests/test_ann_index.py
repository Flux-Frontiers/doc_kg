"""Tests for the row-count-gated IVF (ANN) index in SemanticIndex.

Covers the build-time gate (``_maybe_create_ann_index``), the search-time
probe selection, and the ``_pq_subvectors`` divisor helper. No model is loaded
and no real LanceDB table is created — everything runs against MagicMocks so
the suite stays fast and offline.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from doc_kg.index import (
    _ANN_INDEX_TYPE,
    _ANN_NPROBES,
    _ANN_REFINE_FACTOR,
    SemanticIndex,
    _pq_subvectors,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(
    tmp_path,
    *,
    dim: int = 384,
    ann_threshold: int = 50_000,
    ann_index_type: str = "IVF_PQ",
    ann_nprobes: int = 50,
    ann_refine_factor: int = 0,
):
    """Build a SemanticIndex with a fake embedder, bypassing __init__/model load."""
    idx = SemanticIndex.__new__(SemanticIndex)
    idx.embedder = SimpleNamespace(dim=dim, embed_query=lambda q: [0.0] * dim)
    idx.lancedb_dir = tmp_path / "lancedb"
    idx.table_name = "nodes"
    idx.index_kinds = ("chunk",)
    idx.ann_threshold = ann_threshold
    idx.ann_index_type = ann_index_type
    idx.ann_nprobes = ann_nprobes
    idx.ann_refine_factor = ann_refine_factor
    idx._tbl = None
    idx._has_ann = None
    return idx


def _search_builder(tbl):
    """Wire a chainable MagicMock query builder onto ``tbl.search().metric()``."""
    builder = MagicMock(name="builder")
    builder.nprobes.return_value = builder
    builder.refine_factor.return_value = builder
    builder.where.return_value = builder
    builder.limit.return_value = builder
    builder.to_list.return_value = []
    tbl.search.return_value.metric.return_value = builder
    return builder


# ---------------------------------------------------------------------------
# _pq_subvectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dim", [384, 768, 100, 1024, 17])
def test_pq_subvectors_divides_dim(dim):
    m = _pq_subvectors(dim)
    assert m >= 1
    assert dim % m == 0


def test_pq_subvectors_targets_about_16_dims():
    assert _pq_subvectors(384) == 24  # 384 / 16
    assert _pq_subvectors(768) == 48


def test_default_index_type_is_ivf_flat():
    # IVF_FLAT won the recall/latency bench on the 683k corpus; it is the default.
    assert _ANN_INDEX_TYPE == "IVF_FLAT"


def test_default_refine_factor_is_zero():
    # FLAT keeps full vectors, so refine is a no-op latency tax — default off.
    assert _ANN_REFINE_FACTOR == 0


def test_default_nprobes_is_fifty():
    # Real-query fidelity bench: nprobes=50 gives 0.91 fidelity@10 / 94% top-1
    # retention vs exact, vs 0.83 / 81% at 20 — at no latency cost.
    assert _ANN_NPROBES == 50


# ---------------------------------------------------------------------------
# _maybe_create_ann_index — the build-time gate
# ---------------------------------------------------------------------------


class TestAnnGate:
    def test_below_threshold_skips_index(self, tmp_path):
        idx = _make_index(tmp_path, ann_threshold=50_000)
        tbl = MagicMock()
        tbl.count_rows.return_value = 3_278  # doc_kg-scale corpus
        created = idx._maybe_create_ann_index(tbl, quiet=True)
        assert created is False
        tbl.create_index.assert_not_called()
        assert idx._has_ann is False

    def test_at_or_above_threshold_builds_index(self, tmp_path):
        idx = _make_index(tmp_path, ann_threshold=50_000)
        tbl = MagicMock()
        tbl.count_rows.return_value = 683_001  # gutenberg-all bundle
        created = idx._maybe_create_ann_index(tbl, quiet=True)
        assert created is True
        tbl.create_index.assert_called_once()
        _, kwargs = tbl.create_index.call_args
        assert kwargs["metric"] == "cosine"
        assert kwargs["vector_column_name"] == "vector"
        assert kwargs["num_partitions"] >= 1
        assert idx._has_ann is True

    def test_ivf_pq_passes_num_sub_vectors(self, tmp_path):
        idx = _make_index(tmp_path, ann_index_type="IVF_PQ", dim=384)
        tbl = MagicMock()
        tbl.count_rows.return_value = 100_000
        idx._maybe_create_ann_index(tbl, quiet=True)
        _, kwargs = tbl.create_index.call_args
        assert kwargs["num_sub_vectors"] == 24
        assert 384 % kwargs["num_sub_vectors"] == 0

    def test_ivf_flat_omits_num_sub_vectors(self, tmp_path):
        idx = _make_index(tmp_path, ann_index_type="IVF_FLAT")
        tbl = MagicMock()
        tbl.count_rows.return_value = 100_000
        idx._maybe_create_ann_index(tbl, quiet=True)
        _, kwargs = tbl.create_index.call_args
        assert "num_sub_vectors" not in kwargs

    def test_threshold_zero_disables_index(self, tmp_path):
        idx = _make_index(tmp_path, ann_threshold=0)
        tbl = MagicMock()
        tbl.count_rows.return_value = 1_000_000
        created = idx._maybe_create_ann_index(tbl, quiet=True)
        assert created is False
        tbl.create_index.assert_not_called()
        assert idx._has_ann is False

    def test_num_partitions_sqrt_heuristic(self, tmp_path):
        idx = _make_index(tmp_path, ann_threshold=1)
        tbl = MagicMock()
        tbl.count_rows.return_value = 1_000_000  # sqrt = 1000
        idx._maybe_create_ann_index(tbl, quiet=True)
        _, kwargs = tbl.create_index.call_args
        assert kwargs["num_partitions"] == 1000

    def test_create_index_failure_falls_back_to_flat(self, tmp_path):
        idx = _make_index(tmp_path, ann_threshold=1)
        tbl = MagicMock()
        tbl.count_rows.return_value = 100_000
        tbl.create_index.side_effect = RuntimeError("lancedb said no")
        created = idx._maybe_create_ann_index(tbl, quiet=True)
        assert created is False
        assert idx._has_ann is False  # search will stay on flat scan

    def test_legacy_lancedb_without_index_type_kwarg(self, tmp_path):
        """Older LanceDB rejects index_type=; helper retries without it."""
        idx = _make_index(tmp_path, ann_threshold=1)
        tbl = MagicMock()
        tbl.count_rows.return_value = 100_000

        def _create(*_args, **kwargs):
            if "index_type" in kwargs:
                raise TypeError("unexpected keyword 'index_type'")
            return None

        tbl.create_index.side_effect = _create
        created = idx._maybe_create_ann_index(tbl, quiet=True)
        assert created is True
        assert idx._has_ann is True
        assert tbl.create_index.call_count == 2  # first with index_type, then without


# ---------------------------------------------------------------------------
# _table_has_ann_index — cached probe
# ---------------------------------------------------------------------------


class TestHasAnnIndex:
    def test_uses_cached_value_without_probing(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._has_ann = True
        tbl = MagicMock()
        assert idx._table_has_ann_index(tbl) is True
        tbl.list_indices.assert_not_called()

    def test_probes_when_unknown(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._has_ann = None
        tbl = MagicMock()
        tbl.list_indices.return_value = ["some_index"]
        assert idx._table_has_ann_index(tbl) is True
        assert idx._has_ann is True

    def test_no_index_means_flat(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._has_ann = None
        tbl = MagicMock()
        tbl.list_indices.return_value = []
        assert idx._table_has_ann_index(tbl) is False


# ---------------------------------------------------------------------------
# search — probe selection
# ---------------------------------------------------------------------------


class TestSearchProbeSelection:
    def test_flat_scan_sets_no_probes(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._has_ann = False  # small corpus, no index
        tbl = MagicMock()
        builder = _search_builder(tbl)
        idx._tbl = tbl

        idx.search("hello world", k=8)

        builder.nprobes.assert_not_called()
        builder.refine_factor.assert_not_called()
        builder.limit.assert_called_once_with(8)

    def test_indexed_search_sets_nprobes_and_refine(self, tmp_path):
        idx = _make_index(tmp_path, ann_nprobes=20, ann_refine_factor=10)
        idx._has_ann = True
        tbl = MagicMock()
        builder = _search_builder(tbl)
        idx._tbl = tbl

        idx.search("hello world", k=8)

        builder.nprobes.assert_called_once_with(20)
        builder.refine_factor.assert_called_once_with(10)

    def test_indexed_search_skips_refine_when_zero(self, tmp_path):
        idx = _make_index(tmp_path, ann_refine_factor=0)
        idx._has_ann = True
        tbl = MagicMock()
        builder = _search_builder(tbl)
        idx._tbl = tbl

        idx.search("hello world", k=8)

        builder.nprobes.assert_called_once_with(50)
        builder.refine_factor.assert_not_called()
