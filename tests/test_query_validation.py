"""DocKG.query() and pack() reject bad arguments before touching the index.

The checks come from ``kg_utils.validation`` (kgmodule-utils 0.23.0). DocKG is
not a ``KGModule`` subclass, so it calls them itself rather than inheriting
them; these tests prove the calls are wired at the top of both methods. None
of them needs a built corpus: a rejected argument never reaches the index,
which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doc_kg import DocKG


@pytest.fixture
def kg(tmp_path: Path) -> DocKG:
    """An unbuilt DocKG. Any call that reached the index here would fail loudly."""
    return DocKG(tmp_path)


class TestQuery:
    def test_empty_query_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"q must not be empty"):
            kg.query("   ")

    def test_k_below_one_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"k must be between 1 and 100, got 0"):
            kg.query("stoic philosophy", k=0)

    def test_k_above_limit_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"k must be between 1 and 100, got 101"):
            kg.query("stoic philosophy", k=101)

    def test_hop_above_limit_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"hop must be between 0 and 5, got 6"):
            kg.query("stoic philosophy", hop=6)

    def test_max_nodes_above_limit_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"max_nodes must be between 1 and 500, got 501"):
            kg.query("stoic philosophy", max_nodes=501)


class TestPack:
    def test_empty_query_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"q must not be empty"):
            kg.pack("")

    def test_hop_above_limit_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"hop must be between 0 and 5, got 6"):
            kg.pack("stoic philosophy", hop=6)

    def test_max_nodes_above_limit_raises(self, kg: DocKG) -> None:
        with pytest.raises(ValueError, match=r"max_nodes must be between 1 and 500, got 501"):
            kg.pack("stoic philosophy", max_nodes=501)

    def test_no_node_cap_is_not_rejected(self, kg: DocKG) -> None:
        """pack(max_nodes=None) means no limit; the check must skip it, not raise.

        With no index built the call fails further in, which is what
        distinguishes "the validator let it through" from "the validator
        rejected it": a ValueError naming max_nodes would be the defect.
        """
        with pytest.raises(Exception) as excinfo:
            kg.pack("stoic philosophy", max_nodes=None)
        assert "max_nodes" not in str(excinfo.value)
