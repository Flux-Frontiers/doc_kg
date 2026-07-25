#!/usr/bin/env python3
"""
app.py - DocKG Streamlit Visualizer.

Adapted from CodeKG's app structure for document-oriented nodes and edges.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

# pylint: disable=import-error
import streamlit as st  # type: ignore[import-not-found]
from pyvis.network import Network  # type: ignore[import-not-found]

from doc_kg.kg import DocKG
from doc_kg.store import DEFAULT_RELS, GraphStore

_KIND_COLOR: dict[str, str] = {
    "document": "#2E6BAE",
    "section": "#B8742B",
    "chunk": "#2F8F5B",
    "topic": "#8D6E63",
    "entity": "#CC5A2E",
    "keyword": "#4E7A5E",
}

_KIND_SHAPE: dict[str, str] = {
    "document": "box",
    "section": "diamond",
    "chunk": "ellipse",
    "topic": "dot",
    "entity": "triangle",
    "keyword": "star",
}

_REL_COLOR: dict[str, str] = {
    "CONTAINS": "#A8B3BE",
    "NEXT": "#6FA8DC",
    "REFERENCES": "#D97B5B",
    "SIMILAR_TO": "#6A8D73",
    "HAS_TOPIC": "#8D6E63",
    "MENTIONS_ENTITY": "#CC5A2E",
    "HAS_KEYWORD": "#4E7A5E",
    "CO_OCCURS_WITH": "#9E9E9E",
}

_DEFAULT_DB = os.environ.get("DOCKG_DB", ".dockg/graph.sqlite")
_DEFAULT_LANCEDB = os.environ.get("DOCKG_LANCEDB", ".dockg/lancedb")


st.set_page_config(
    page_title="DocKG Explorer",
    page_icon="\N{SPIDER WEB}",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _parse_cli_db_arg() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", default=None)
    args, _ = parser.parse_known_args()
    return args.db


def _init_state() -> None:
    defaults = {
        "db_path": _parse_cli_db_arg() or _DEFAULT_DB,
        "store": None,
        "store_loaded_path": None,
        "query_result": None,
        "pack_result": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.cache_resource(show_spinner="Opening SQLite store...")
def _load_store(db_path: str) -> GraphStore | None:
    p = Path(db_path)
    if not p.exists():
        return None
    return GraphStore(db_path)


@st.cache_resource(show_spinner="Loading DocKG...")
def _load_kg(corpus_root: str, db_path: str, lancedb_dir: str, model: str) -> DocKG:
    return DocKG(
        corpus_root=corpus_root,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model,
    )


def _get_store() -> GraphStore | None:
    db = st.session_state.db_path
    if st.session_state.store_loaded_path != db:
        st.session_state.store = _load_store(db)
        st.session_state.store_loaded_path = db
    return st.session_state.store


def _build_pyvis(
    nodes: list[dict],
    edges: list[dict],
    *,
    height: str = "620px",
    seed_ids: set[str] | None = None,
    physics: bool = True,
) -> str:
    net = Network(
        height=height,
        width="100%",
        bgcolor="#0e1117",
        font_color="#e0e0e0",
        directed=True,
        notebook=False,
        # pyvis defaults to cdn_resources="local", which emits *relative* asset
        # paths (lib/bindings/utils.js, ../node_modules/vis/dist/vis.js) plus a
        # cdnjs fallback, and writes a lib/ directory into the current working
        # directory on every render.  Streamlit embeds this HTML in a srcdoc
        # iframe, which has no base URL, so the relative paths cannot resolve —
        # the graph renders only when cdnjs is reachable at view time and
        # otherwise fails silently with "vis is not defined".  "in_line" inlines
        # vis-network so the page is self-contained and nothing hits disk.
        cdn_resources="in_line",
    )
    net.set_options(
        json.dumps(
            {
                "physics": {
                    "enabled": physics,
                    "barnesHut": {
                        "gravitationalConstant": -8000,
                        "centralGravity": 0.25,
                        "springLength": 130,
                        "springConstant": 0.04,
                        "damping": 0.09,
                    },
                    "stabilization": {"iterations": 150},
                },
                "edges": {
                    "smooth": {"type": "dynamic"},
                    "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
                    "font": {"size": 10, "color": "#aaaaaa"},
                },
                "interaction": {
                    "hover": True,
                    "tooltipDelay": 80,
                    "navigationButtons": True,
                    "keyboard": True,
                },
            }
        )
    )

    seeds = seed_ids or set()

    for n in nodes:
        kind = n.get("kind", "chunk")
        color = _KIND_COLOR.get(kind, "#95A5A6")
        shape = _KIND_SHAPE.get(kind, "dot")
        label = n.get("title") or n.get("name") or n["id"]
        if len(label) > 32:
            label = label[:29] + "..."

        title = (
            f"<b>{kind}</b><br>"
            f"id: {n.get('id', '')}<br>"
            f"file: {n.get('file_path') or '-'}<br>"
            f"name/title: {n.get('title') or n.get('name') or '-'}"
        )

        border_color = "#FFD700" if n["id"] in seeds else color

        net.add_node(
            n["id"],
            label=label,
            title=title,
            color={
                "background": color,
                "border": border_color,
                "highlight": {"background": color, "border": "#FFFFFF"},
            },
            shape=shape,
            size=18 if kind in ("document", "section") else 12,
            borderWidth=3 if n["id"] in seeds else 1,
            font={"size": 11},
        )

    for e in edges:
        rel = e.get("rel", "")
        ecolor = _REL_COLOR.get(rel, "#888888")
        net.add_edge(
            e["src"],
            e["dst"],
            label=rel,
            color=ecolor,
            width=1.5,
            title=rel,
        )

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        tmp_path = f.name
    net.save_graph(tmp_path)
    html = Path(tmp_path).read_text(encoding="utf-8")
    os.unlink(tmp_path)
    return html


def _render_sidebar() -> dict:
    st.sidebar.title("DocKG Explorer")
    st.sidebar.markdown("---")

    db_path = st.sidebar.text_input("SQLite path", value=st.session_state.db_path)
    st.session_state.db_path = db_path

    store = _get_store()
    if store is None:
        st.sidebar.warning(f"{db_path} not found. Build your graph first.")
    else:
        s = store.stats()
        st.sidebar.success(f"{s['total_nodes']} nodes / {s['total_edges']} edges")

    st.sidebar.markdown("---")
    corpus_root = st.sidebar.text_input("Corpus root", value=str(Path.cwd()))
    lancedb_dir = st.sidebar.text_input("LanceDB dir", value=_DEFAULT_LANCEDB)
    model = st.sidebar.selectbox(
        "Embedding model",
        [
            "all-MiniLM-L6-v2",
            "all-mpnet-base-v2",
            "paraphrase-MiniLM-L3-v2",
        ],
        index=0,
    )

    k = st.sidebar.slider("Top-k seeds", min_value=1, max_value=30, value=8)
    hop = st.sidebar.slider("Graph hops", min_value=0, max_value=4, value=1)
    chosen_rels = st.sidebar.multiselect(
        "Edge relations",
        options=list(DEFAULT_RELS),
        default=list(DEFAULT_RELS),
    )

    st.sidebar.markdown("---")
    max_graph_nodes = st.sidebar.slider("Max graph nodes", 20, 400, 140, step=10)
    physics_on = st.sidebar.checkbox("Physics simulation", value=True)
    graph_height = st.sidebar.select_slider(
        "Graph height",
        options=["400px", "500px", "620px", "750px"],
        value="620px",
    )

    return {
        "db_path": db_path,
        "store": store,
        "corpus_root": corpus_root,
        "lancedb_dir": lancedb_dir,
        "model": model,
        "k": k,
        "hop": hop,
        "rels": tuple(chosen_rels),
        "max_graph_nodes": max_graph_nodes,
        "physics_on": physics_on,
        "graph_height": graph_height,
    }


def _load_all_nodes_edges(store: GraphStore, max_nodes: int) -> tuple[list[dict], list[dict]]:
    rows = store.con.execute(
        """
        SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text
        FROM nodes
        ORDER BY kind, file_path, char_start
        LIMIT ?
        """,
        (max_nodes,),
    ).fetchall()

    nodes = [
        {
            "id": r[0],
            "kind": r[1],
            "name": r[2],
            "title": r[3],
            "file_path": r[4],
            "char_start": r[5],
            "char_end": r[6],
            "heading_level": r[7],
            "text": r[8],
        }
        for r in rows
    ]
    node_ids = {n["id"] for n in nodes}
    edges = store.edges_within(node_ids)
    return nodes, edges


def main() -> None:
    """Streamlit app entry point — initialise state, render sidebar and main view."""
    _init_state()
    cfg = _render_sidebar()

    st.title("DocKG Explorer")
    st.caption("Interactive graph, query, and text-pack inspection for document corpora.")

    tab_graph, tab_query, tab_pack = st.tabs(["Graph", "Query", "Pack"])

    with tab_graph:
        if cfg["store"] is None:
            st.info("Set a valid SQLite path to explore the graph.")
        else:
            nodes, edges = _load_all_nodes_edges(cfg["store"], cfg["max_graph_nodes"])
            html = _build_pyvis(
                nodes,
                edges,
                height=cfg["graph_height"],
                physics=cfg["physics_on"],
            )
            st.components.v1.html(html, height=int(cfg["graph_height"].replace("px", "")) + 30)
            st.caption(f"Showing {len(nodes)} nodes and {len(edges)} edges.")

    with tab_query:
        q = st.text_input("Query", value="knowledge graph architecture")
        if st.button("Run Query"):
            try:
                kg = _load_kg(
                    cfg["corpus_root"],
                    cfg["db_path"],
                    cfg["lancedb_dir"],
                    cfg["model"],
                )
                result = kg.query(
                    q,
                    k=cfg["k"],
                    hop=cfg["hop"],
                    rels=cfg["rels"],
                    max_nodes=cfg["max_graph_nodes"],
                )
                st.session_state.query_result = result
            except (
                AttributeError,
                ValueError,
                RuntimeError,
                OSError,
            ) as exc:  # pragma: no cover
                st.error(f"Query failed: {exc}")

        if st.session_state.query_result:
            result = st.session_state.query_result
            st.write(
                f"Seeds: {result.seeds} | Expanded: {result.expanded_nodes}"
                f" | Returned: {result.returned_nodes}"
            )
            st.json(result.to_dict())

            html = _build_pyvis(
                result.nodes,
                result.edges,
                height=cfg["graph_height"],
                seed_ids={n["id"] for n in result.nodes[: cfg["k"]]},
                physics=cfg["physics_on"],
            )
            st.components.v1.html(html, height=int(cfg["graph_height"].replace("px", "")) + 30)

    with tab_pack:
        pquery = st.text_input("Pack query", value="MCP setup and usage")
        max_chars = st.slider("Max chars per excerpt", 200, 5000, 1500, step=100)

        if st.button("Build Pack"):
            try:
                kg = _load_kg(
                    cfg["corpus_root"],
                    cfg["db_path"],
                    cfg["lancedb_dir"],
                    cfg["model"],
                )
                pack = kg.pack(
                    pquery,
                    k=cfg["k"],
                    hop=cfg["hop"],
                    rels=cfg["rels"],
                    max_chars=max_chars,
                    max_nodes=20,
                )
                st.session_state.pack_result = pack
            except (
                AttributeError,
                ValueError,
                RuntimeError,
                OSError,
            ) as exc:  # pragma: no cover
                st.error(f"Pack failed: {exc}")

        if st.session_state.pack_result:
            pack = st.session_state.pack_result
            st.download_button(
                "Download Markdown",
                data=pack.to_markdown(),
                file_name="dockg_pack.md",
                mime="text/markdown",
            )
            st.download_button(
                "Download JSON",
                data=pack.to_json(),
                file_name="dockg_pack.json",
                mime="application/json",
            )
            st.markdown(pack.to_markdown())


if __name__ == "__main__":
    main()
