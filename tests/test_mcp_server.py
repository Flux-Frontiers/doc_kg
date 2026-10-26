"""tests/test_mcp_server.py

The DocKG MCP server on the fleet's shared base, ``kg_utils.mcp``.

Import-level regression tests first: the server's import of ``mcp`` breaks at
import time, not call time, when an incompatible ``mcp`` release is installed
(mcp 2.0 removed ``mcp.server.fastmcp``), and only for people installing from
PyPI.

Then the surface step 3 of kgrag_priv's MCP centralization plan promises: the
five canonical tools under the same names as every fleet server; ``query`` and
``pack`` keep DocKG's own search (``max_chars``, ``traced``); the manifest
answers without a graph; ``dockg``'s other commands do not import ``mcp``; the
session banner reports the store actually serving; a repository with no graph
is refused; and a real stdio subprocess serves.

Driven through a real MCP client: ``mcp.shared.memory``'s in-process session
for behaviour, a subprocess for stdio. No model is loaded except in the one
test marked ``integration``.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from click.testing import CliRunner
from kg_utils.mcp import CANONICAL_TOOLS, manifest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

import doc_kg
from doc_kg.cli.main import cli
from doc_kg.dockg import DocEdge, DocNode
from doc_kg.mcp_server import SERVER_RELS, build_server
from doc_kg.store import GraphStore

_SRC = str(Path(doc_kg.__file__).resolve().parents[1])


def _node(nid: str, kind: str, **kw) -> DocNode:
    return DocNode(
        id=nid,
        kind=kind,
        name=kw.get("name", nid),
        title=kw.get("title"),
        file_path=kw.get("file_path", "a.md"),
        char_start=0,
        char_end=10,
        heading_level=None,
        text=kw.get("text", nid),
    )


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A built graph -- one document, a section, two chunks -- and no vectors."""
    store = GraphStore(tmp_path / ".dockg" / "graph.sqlite")
    store.write(
        [
            _node("doc:a.md", "document", title="A"),
            _node("sec:a.md:intro", "section", title="Intro"),
            _node("chunk:a.md:0000", "chunk", text="whales sing"),
            _node("chunk:a.md:0001", "chunk", text="rockets fly"),
        ],
        [
            DocEdge(src="doc:a.md", rel="CONTAINS", dst="sec:a.md:intro"),
            DocEdge(src="sec:a.md:intro", rel="CONTAINS", dst="chunk:a.md:0000"),
            DocEdge(src="sec:a.md:intro", rel="CONTAINS", dst="chunk:a.md:0001"),
            DocEdge(src="chunk:a.md:0000", rel="NEXT", dst="chunk:a.md:0001"),
        ],
        quiet=True,
    )
    store.close()
    return tmp_path


def _session(server, fn):
    async def main():
        async with create_connected_server_and_client_session(server) as client:
            return await fn(client)

    return anyio.run(main)


# ---------------------------------------------------------------------------
# Import level
# ---------------------------------------------------------------------------


def test_server_module_imports():
    """The module must import cleanly against the installed mcp release."""
    importlib.import_module("doc_kg.mcp_server")


def test_fastmcp_import_path_exists():
    """``mcp.server.fastmcp`` must exist -- mcp 2.0 removed it."""
    importlib.import_module("mcp.server.fastmcp")


def test_entry_point_target_exists():
    """``dockg-mcp`` resolves to doc_kg.mcp_server:main."""
    assert callable(importlib.import_module("doc_kg.mcp_server").main)


# ---------------------------------------------------------------------------
# The tool surface
# ---------------------------------------------------------------------------


def test_exactly_the_canonical_tools(tmp_path):
    assert [t["name"] for t in manifest(build_server(tmp_path))["tools"]] == list(CANONICAL_TOOLS)


def test_query_and_pack_keep_doc_kgs_own_search(tmp_path):
    props = {
        t["name"]: t["input_schema"]["properties"]
        for t in manifest(build_server(tmp_path))["tools"]
    }
    assert {"max_chars", "traced"} <= set(props["pack"])
    assert "context" not in props["pack"] and "min_score" not in props["query"]


def test_graph_tools_answer_without_a_model(corpus, monkeypatch):
    """stats, get_node and neighbors read the graph only."""

    def refuse(*_a, **_k):
        raise RuntimeError("embedding model load refused by test")

    monkeypatch.setattr("doc_kg.kg.make_embedder", refuse)

    async def calls(client: ClientSession):
        return (
            await client.call_tool("stats", {}),
            await client.call_tool("get_node", {"node_id": "sec:a.md:intro"}),
            await client.call_tool(
                "neighbors", {"node_id": "sec:a.md:intro", "rels": ["CONTAINS"], "direction": "out"}
            ),
            await client.call_tool("get_node", {"node_id": "nope"}),
            await client.call_tool("query", {"q": "whales"}),
        )

    stats, node, near, missing, query = _session(build_server(corpus), calls)
    assert not stats.isError and stats.structuredContent["nodes"]["total"] == 4
    assert not node.isError and node.structuredContent["title"] == "Intro"
    assert [n["id"] for n in near.structuredContent["nodes"]] == [
        "chunk:a.md:0000",
        "chunk:a.md:0001",
    ]
    assert missing.isError and "no node with id 'nope'" in missing.content[0].text
    assert query.isError and "embedding model load refused by test" in query.content[0].text


def test_server_relations_include_co_occurs_with():
    assert "CO_OCCURS_WITH" in SERVER_RELS and "CONTAINS" in SERVER_RELS


# ---------------------------------------------------------------------------
# Session lifecycle and the banner
# ---------------------------------------------------------------------------


def test_banner_reports_the_store_actually_serving(corpus, capsys):
    """Not "default": the resolved paths, as the old banner tests demanded."""
    _session(build_server(corpus), lambda c: c.call_tool("stats", {}))
    err = capsys.readouterr().err
    assert "\\n" not in err
    assert "dockg: serving" in err
    assert f"vectors : {corpus.resolve() / '.dockg' / 'vectors.sqlite'}" in err
    assert f"db      : {corpus.resolve() / '.dockg' / 'graph.sqlite'}" in err


def test_banner_honours_an_explicit_vectors_path(corpus, capsys):
    custom = corpus / "elsewhere" / "vectors.sqlite"
    _session(build_server(corpus, vectors=custom), lambda c: c.call_tool("stats", {}))
    assert f"vectors : {custom}" in capsys.readouterr().err


def test_a_corpus_without_a_graph_is_refused_not_served_empty(tmp_path):
    with pytest.raises(BaseException) as info:  # noqa: PT011 -- ExceptionGroup from the task group
        _session(build_server(tmp_path), lambda c: c.call_tool("stats", {}))
    assert "no graph at" in repr(info.value) or any(
        "no graph at" in str(e) for e in getattr(info.value, "exceptions", ())
    )
    assert not (tmp_path / ".dockg" / "graph.sqlite").exists()


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_manifest_answers_without_a_graph_and_creates_nothing(tmp_path):
    result = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--manifest"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["canonical"] == list(CANONICAL_TOOLS)
    assert not (tmp_path / ".dockg").exists()


def test_both_entry_points_are_the_same_command(tmp_path):
    via_cli = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--manifest"]).output
    via_script = subprocess.run(
        [
            sys.executable,
            "-c",
            "from doc_kg.mcp_server import main; main()",
            "--repo",
            str(tmp_path),
            "--manifest",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(via_cli) == json.loads(via_script)


def test_sse_and_lancedb_flags_are_gone(tmp_path):
    for flag in (["--transport", "sse"], ["--lancedb", "x"], ["--vectors-path", "x"]):
        result = CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), *flag, "--manifest"])
        assert result.exit_code == 2, flag


def test_other_commands_do_not_import_mcp():
    out = subprocess.run(
        [sys.executable, "-c", "import sys, doc_kg.cli.main; print('mcp' in sys.modules)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "False"


def test_stdio_subprocess_serves(corpus):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from doc_kg.mcp_server import main; main()", "--repo", str(corpus)],
        env={**os.environ, "PYTHONPATH": _SRC},
    )

    async def run():
        with open(corpus / "stderr.log", "w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as client:
                    init = await client.initialize()
                    tools = await client.list_tools()
                    stats = await client.call_tool("stats", {})
                    return init, tools, stats

    init, tools, stats = anyio.run(run)
    assert (init.serverInfo.name, init.serverInfo.version) == ("dockg", doc_kg.__version__)
    assert [t.name for t in tools.tools] == list(CANONICAL_TOOLS)
    assert stats.structuredContent["nodes"]["total"] == 4
    err = (corpus / "stderr.log").read_text(encoding="utf-8")
    assert "dockg MCP server starting (stdio)" in err and "dockg: serving" in err


# ---------------------------------------------------------------------------
# query and pack end to end, with a deterministic embedder (no model download)
# ---------------------------------------------------------------------------


class _KeywordEmbedder:
    """One dimension per keyword, plus a constant so no vector is zero."""

    _words = ("whale", "rocket", "song", "fuel")
    dim = len(_words) + 1
    model_name = "keyword-test"

    def embed_texts(self, texts, encode_batch_size: int = 128):
        return [[float(w in t.lower()) for w in self._words] + [0.01] for t in texts]

    def embed_query(self, query: str):
        return self.embed_texts([query])[0]


def test_query_and_pack_through_mcp(tmp_path, monkeypatch):
    from doc_kg import DocKG

    monkeypatch.setattr("doc_kg.kg.make_embedder", lambda *_a, **_k: _KeywordEmbedder())
    (tmp_path / "whales.md").write_text("# Whales\n\nHumpback whales sing long songs.\n")
    (tmp_path / "rockets.md").write_text("# Rockets\n\nRockets burn fuel to fly.\n")
    kg = DocKG(
        tmp_path,
        chunk_strategy="fixed",
        enable_topics=False,
        enable_entities=False,
        enable_keywords=False,
    )
    kg.build(wipe=True, discover_similar=False)
    kg.close()

    async def calls(client: ClientSession):
        return (
            await client.call_tool("query", {"q": "whale songs", "k": 3}),
            await client.call_tool("pack", {"q": "whale songs", "k": 3, "traced": True}),
            await client.call_tool("query", {"q": "whale songs", "rels": ["NEXT"]}),
        )

    found, packed, narrowed = _session(build_server(tmp_path), calls)
    assert not found.isError and found.structuredContent["returned_nodes"] >= 1
    assert "whales.md" in found.structuredContent["nodes"][0]["file_path"]
    assert not packed.isError and "whales sing" in packed.content[0].text.lower()
    assert narrowed.structuredContent["rels"] == ["NEXT"]
