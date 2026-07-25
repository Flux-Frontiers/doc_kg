"""
test_app_render.py

Guards the self-containment of the pyvis page built by :mod:`doc_kg.app`.
Requires the ``viz`` extra and is skipped without it.

pyvis defaults to ``cdn_resources="local"``, which emits *relative* asset paths
and writes a ``lib/`` directory into the current working directory on every
render.  Streamlit embeds the page in a ``srcdoc`` iframe, which has no base
URL, so those paths cannot resolve — the graph then renders only when
``cdnjs.cloudflare.com`` is reachable at view time, and otherwise fails silently
with ``vis is not defined`` and a blank panel.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyvis")

import streamlit as st  # noqa: E402

# Importing app.py runs st.set_page_config at module scope, which is only legal
# inside a `streamlit run` process.
st.set_page_config = lambda **kwargs: None  # type: ignore[assignment]

from doc_kg.app import _build_pyvis  # noqa: E402

NODES = [
    {"id": "doc:guide.md", "kind": "document", "name": "guide", "title": "Guide"},
    {"id": "sec:guide.md:1", "kind": "section", "name": "intro", "title": "Intro"},
    {"id": "chk:guide.md:1", "kind": "chunk", "name": "chunk-1", "title": "Chunk 1"},
]
EDGES = [
    {"src": "doc:guide.md", "rel": "CONTAINS", "dst": "sec:guide.md:1"},
    {"src": "sec:guide.md:1", "rel": "CONTAINS", "dst": "chk:guide.md:1"},
]


def test_vis_library_is_inlined_not_cdn_linked() -> None:
    """The graph must not depend on reaching cdnjs to render."""
    html = _build_pyvis(NODES, EDGES)
    assert "cdnjs.cloudflare.com/ajax/libs/vis-network" not in html


def test_no_relative_script_that_the_graph_depends_on() -> None:
    """The bindings shim must be inlined, not referenced by relative path."""
    html = _build_pyvis(NODES, EDGES)
    assert 'src="lib/bindings/utils.js"' not in html


def test_vis_source_is_present() -> None:
    """The page really carries the vis-network implementation."""
    html = _build_pyvis(NODES, EDGES)
    assert "vis-network" in html
    assert len(html) > 500_000, "inlined bundle should dominate the payload"


def test_render_writes_nothing_to_the_working_directory(tmp_path, monkeypatch) -> None:
    """Building a graph must not litter the user's repo with a lib/ directory."""
    monkeypatch.chdir(tmp_path)
    _build_pyvis(NODES, EDGES)
    assert list(tmp_path.iterdir()) == []


def test_every_node_reaches_the_page() -> None:
    """A sanity check that the payload is actually populated."""
    html = _build_pyvis(NODES, EDGES)
    for node in NODES:
        assert node["id"] in html
