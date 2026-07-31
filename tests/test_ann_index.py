"""Tests for DocKG's ANN configuration and backend delegation.

The IVF (ANN) *mechanics* — the row-count gate, num_partitions heuristic,
IVF_PQ sub-vector count, and search-time probe selection — moved to
``kg_utils.vector_backend.LanceDBBackend`` (tested in kg_utils'
test_vector_backend.py). What remains DocKG's responsibility, and is covered
here, is:

  * the ``_ANN_*`` default constants,
  * that ``SemanticIndex`` defaults to a ``SqliteVecBackend`` at the sidecar
    (changed in 0.20.0 — it used to default to ``LanceDBBackend``, which is no
    longer installed by default), and
  * that a ``SqliteVecBackend``-backed index does no ANN (the exact,
    always-flat sqlite-vec path).

The ``_ANN_*`` constants remain meaningful: they are threaded into a
``LanceDBBackend`` only when one is asked for explicitly, via ``make_backend``.

No model is loaded — the index is built via ``__new__`` with a fake embedder.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from kg_utils.vector_backend import LanceDBBackend, SqliteVecBackend, _pq_subvectors

from doc_kg.index import (
    _ANN_INDEX_TYPE,
    _ANN_NPROBES,
    _ANN_REFINE_FACTOR,
    _META_COLUMNS,
    SemanticIndex,
    make_backend,
    sqlite_vectors_path,
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


def test_default_backend_is_sqlite_vec_at_the_sidecar(tmp_path):
    """Changed in 0.20.0: the implicit backend is sqlite-vec, not LanceDB.

    A bare ``SemanticIndex`` must not reach for a dependency that is no longer
    installed by default, and the store it picks must be the same sidecar
    ``make_backend`` derives — ``<lancedb_dir>.parent/vectors.sqlite``.
    """
    idx = _make_index(tmp_path)
    be = idx._get_backend()
    assert isinstance(be, SqliteVecBackend)
    assert not isinstance(be, LanceDBBackend)
    assert be.meta_columns == _META_COLUMNS
    assert Path(be.db_path) == sqlite_vectors_path(idx.lancedb_dir)


def test_ann_config_still_reaches_an_explicit_lancedb_backend(tmp_path):
    """The _ANN_* defaults are not dead — they apply when LanceDB is requested."""
    pytest.importorskip("lancedb", reason="optional [lancedb] extra not installed")
    be = make_backend(
        "lancedb",
        lancedb_dir=tmp_path / "lancedb",
        dim=384,
        table="nodes",
        ann_threshold=50_000,
        ann_index_type=_ANN_INDEX_TYPE,
        ann_nprobes=_ANN_NPROBES,
        ann_refine_factor=_ANN_REFINE_FACTOR,
    )
    assert isinstance(be, LanceDBBackend)
    assert be.ann_threshold == 50_000
    assert be.ann_index_type == "IVF_FLAT"
    assert be.ann_nprobes == 50
    assert be.ann_refine_factor == 0
    assert be.meta_columns == _META_COLUMNS


def test_lancedb_backend_errors_actionably_when_extra_missing(tmp_path):
    """Without the extra, asking for LanceDB must say how to get it."""
    if importlib.util.find_spec("lancedb") is not None:
        pytest.skip("lancedb installed — the missing-extra path cannot be exercised")
    with pytest.raises(ImportError, match=r"doc-kg\[lancedb\]"):
        make_backend("lancedb", lancedb_dir=tmp_path / "lancedb", dim=384, table="nodes")


def test_explicit_backend_is_used(tmp_path):
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    assert idx._get_backend() is sb


# ---------------------------------------------------------------------------
# sqlite-vec is always exact — ANN finalize is a no-op
# ---------------------------------------------------------------------------


def test_sqlite_backend_has_no_lance_table(tmp_path):
    pytest.importorskip("sqlite_vec")
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    sb.open(wipe=True)
    assert idx._lance_table() is None


def test_finalize_backend_is_noop_on_sqlite(tmp_path):
    pytest.importorskip("sqlite_vec")
    sb = SqliteVecBackend(tmp_path / "v.sqlite", dim=384, meta_columns=_META_COLUMNS)
    idx = _make_index(tmp_path, backend=sb)
    sb.open(wipe=True)
    # Must not raise and must not attempt any IVF index build.
    idx._finalize_backend(quiet=True)
    assert sb.count() == 0
