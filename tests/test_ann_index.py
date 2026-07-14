"""Tests for DocKG's ANN configuration and backend delegation.

The IVF (ANN) *mechanics* — the row-count gate, num_partitions heuristic,
IVF_PQ sub-vector count, and search-time probe selection — moved to
``kg_utils.vector_backend.LanceDBBackend`` (tested in kg_utils'
test_vector_backend.py). What remains DocKG's responsibility, and is covered
here, is:

  * the ``_ANN_*`` default constants,
  * that ``SemanticIndex`` threads those defaults into a ``LanceDBBackend`` by
    default, and
  * that a ``SqliteVecBackend``-backed index does no ANN (the exact,
    always-flat sqlite-vec path).

No model is loaded — the index is built via ``__new__`` with a fake embedder.
"""

from __future__ import annotations

from types import SimpleNamespace

from kg_utils.vector_backend import LanceDBBackend, SqliteVecBackend, _pq_subvectors

from doc_kg.index import (
    _ANN_INDEX_TYPE,
    _ANN_NPROBES,
    _ANN_REFINE_FACTOR,
    _META_COLUMNS,
    SemanticIndex,
)


def _make_index(
    tmp_path,
    *,
    dim=384,
    ann_threshold=50_000,
    ann_index_type="IVF_FLAT",
    ann_nprobes=50,
    ann_refine_factor=0,
    backend=None,
):
    """A SemanticIndex with a fake embedder, bypassing __init__/model load."""
    idx = SemanticIndex.__new__(SemanticIndex)
    idx.embedder = SimpleNamespace(dim=dim, embed_query=lambda q: [0.0] * dim)
    idx.lancedb_dir = tmp_path / "lancedb"
    idx.table_name = "nodes"
    idx.index_kinds = ("chunk",)
    idx.ann_threshold = ann_threshold
    idx.ann_index_type = ann_index_type
    idx.ann_nprobes = ann_nprobes
    idx.ann_refine_factor = ann_refine_factor
    idx._backend = backend
    return idx


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------


def test_default_index_type_is_ivf_flat():
    # IVF_FLAT won the recall/latency bench on the 683k corpus; it is the default.
    assert _ANN_INDEX_TYPE == "IVF_FLAT"


def test_default_refine_factor_is_zero():
    assert _ANN_REFINE_FACTOR == 0


def test_default_nprobes_is_fifty():
    assert _ANN_NPROBES == 50


def test_pq_subvectors_divisor_helper():
    # Re-exported location check: the helper now lives in kg_utils.
    assert _pq_subvectors(384) == 24
    assert 384 % _pq_subvectors(384) == 0


# ---------------------------------------------------------------------------
# Backend delegation
# ---------------------------------------------------------------------------


def test_default_backend_is_lancedb_with_ann_config(tmp_path):
    idx = _make_index(
        tmp_path,
        ann_threshold=50_000,
        ann_index_type="IVF_FLAT",
        ann_nprobes=50,
        ann_refine_factor=0,
    )
    be = idx._get_backend()
    assert isinstance(be, LanceDBBackend)
    assert be.ann_threshold == 50_000
    assert be.ann_index_type == "IVF_FLAT"
    assert be.ann_nprobes == 50
    assert be.ann_refine_factor == 0
    assert be.meta_columns == _META_COLUMNS


def test_explicit_backend_is_used(tmp_path):
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    assert idx._get_backend() is sb


# ---------------------------------------------------------------------------
# sqlite-vec is always exact — ANN finalize is a no-op
# ---------------------------------------------------------------------------


def test_sqlite_backend_has_no_lance_table(tmp_path):
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    sb.open(wipe=True)
    assert idx._lance_table() is None


def test_finalize_backend_is_noop_on_sqlite(tmp_path):
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    sb.open(wipe=True)
    # Must not raise and must not attempt any IVF index build.
    idx._finalize_backend(quiet=True)
    assert sb.count() == 0
