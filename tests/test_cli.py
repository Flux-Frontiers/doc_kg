"""CLI smoke tests for Click command registration."""

import pytest
from click.testing import CliRunner

from doc_kg.cli.main import cli
from doc_kg.dockg import DocEdge, DocNode
from doc_kg.store import GraphStore


def _seed_db(db_path):
    nodes = [
        DocNode(
            id="doc:a.md",
            kind="document",
            name="a",
            title="A",
            file_path="a.md",
            char_start=0,
            char_end=100,
            heading_level=None,
            text="body",
        ),
        DocNode(
            id="chunk:a.md:0",
            kind="chunk",
            name="chunk:0",
            title="Intro",
            file_path="a.md",
            char_start=0,
            char_end=100,
            heading_level=None,
            text="text",
        ),
    ]
    edges = [DocEdge(src="doc:a.md", rel="CONTAINS", dst="chunk:a.md:0")]
    store = GraphStore(db_path)
    store.write(nodes, edges, wipe=True)
    store.stamp_meta("doc_kg", "9.9.9")
    store.close()


def test_cli_includes_expected_commands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "build" in result.output
    assert "build-graph" in result.output
    assert "build-index" in result.output
    assert "query" in result.output
    assert "pack" in result.output
    assert "analyze" in result.output
    assert "snapshot" in result.output
    assert "viz" in result.output
    assert "mcp" in result.output


def test_cli_includes_pipeline_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "pipeline" in result.output


def test_cli_includes_status_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.output


def test_status_command_shows_builder_info(tmp_path):
    db = tmp_path / "graph.sqlite"
    _seed_db(db)

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--repo", str(tmp_path), "--sqlite", str(db)])
    assert result.exit_code == 0
    assert "9.9.9" in result.output
    assert "doc_kg" in result.output
    assert "document" in result.output
    assert "chunk" in result.output


def test_status_command_missing_db(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["status", "--repo", str(tmp_path), "--sqlite", str(tmp_path / "missing.sqlite")]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "not found" in (result.output + "").lower()


# ---------------------------------------------------------------------------
# download-model command
# ---------------------------------------------------------------------------


def test_download_model_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "download-model" in result.output


def test_download_model_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["download-model", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.output
    assert "--force" in result.output


def test_download_model_already_cached(tmp_path):
    """When the model path already exists, report cached and exit cleanly."""
    from unittest.mock import patch

    with patch("doc_kg.cli.cmd_model.resolve_model_path", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["download-model"])
    assert result.exit_code == 0
    assert "cached" in result.output.lower()
    assert "--force" in result.output


def test_download_model_force_redownloads(tmp_path):
    """--force bypasses the cached-path check and saves the model."""
    from unittest.mock import MagicMock, patch

    mock_st_instance = MagicMock()
    with (
        patch("doc_kg.cli.cmd_model.resolve_model_path", return_value=tmp_path / "model"),
        patch("sentence_transformers.SentenceTransformer", return_value=mock_st_instance),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["download-model", "--force"])
    assert result.exit_code == 0
    assert "downloading" in result.output.lower() or "saved" in result.output.lower()
    mock_st_instance.save.assert_called_once()


def test_download_model_saves_to_path(tmp_path):
    """Model is saved to the resolved local path."""
    from unittest.mock import MagicMock, patch

    save_target = tmp_path / "BAAI" / "bge-small-en-v1.5"
    mock_st_instance = MagicMock()
    with (
        patch("doc_kg.cli.cmd_model.resolve_model_path", return_value=save_target),
        patch("sentence_transformers.SentenceTransformer", return_value=mock_st_instance),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["download-model", "--model", "BAAI/bge-small-en-v1.5"])
    assert result.exit_code == 0
    mock_st_instance.save.assert_called_once_with(str(save_target))


# ---------------------------------------------------------------------------
# --vectors-path wiring
#
# The option must reach DocKG(vectors_path=...) on every command that touches
# the vector store, and must stay off the graph-only commands.
# ---------------------------------------------------------------------------

_VECTORS_PATH_COMMANDS = [
    ["build"],
    ["build-index"],
    ["build-index-from-cache"],
    ["build-two-phase"],
    ["query"],
    ["pack"],
    ["mcp"],
    ["snapshot", "save"],
]

# Graph-only commands: no vector store is read or written, so the option would
# be misleading noise.
_NO_VECTORS_PATH_COMMANDS = [
    ["build-graph"],
    ["build-embeddings"],
    ["status"],
    ["reindex-fts"],
]


@pytest.mark.parametrize("command", _VECTORS_PATH_COMMANDS, ids=lambda c: "-".join(c))
def test_vectors_path_option_exposed(command):
    result = CliRunner().invoke(cli, command + ["--help"])
    assert result.exit_code == 0, result.output
    assert "--vectors-path" in result.output


@pytest.mark.parametrize("command", _NO_VECTORS_PATH_COMMANDS, ids=lambda c: "-".join(c))
def test_vectors_path_option_absent_on_graph_only_commands(command):
    result = CliRunner().invoke(cli, command + ["--help"])
    assert result.exit_code == 0, result.output
    assert "--vectors-path" not in result.output


def test_query_forwards_vectors_path_to_dockg(tmp_path):
    """Parsing the flag is not enough — it must reach the DocKG constructor."""
    from unittest.mock import MagicMock, patch

    db = tmp_path / ".dockg" / "graph.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    custom = tmp_path / "offsite" / "vectors.sqlite"

    with patch("doc_kg.cli.cmd_query.DocKG") as mock_kg:
        mock_kg.return_value = MagicMock()
        CliRunner().invoke(
            cli,
            [
                "query",
                "--repo",
                str(tmp_path),
                "--sqlite",
                str(db),
                "--vectors-path",
                str(custom),
                "whale",
            ],
        )

    assert mock_kg.call_args is not None, "DocKG was never constructed"
    assert mock_kg.call_args.kwargs["vectors_path"] == str(custom)


def test_query_defaults_vectors_path_to_none(tmp_path):
    """Omitting the flag must keep the derived-sidecar behaviour."""
    from unittest.mock import MagicMock, patch

    db = tmp_path / ".dockg" / "graph.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    with patch("doc_kg.cli.cmd_query.DocKG") as mock_kg:
        mock_kg.return_value = MagicMock()
        CliRunner().invoke(cli, ["query", "--repo", str(tmp_path), "--sqlite", str(db), "whale"])

    assert mock_kg.call_args.kwargs["vectors_path"] is None


def test_mcp_forwards_vectors_path_through_argv(tmp_path):
    """The mcp command shells out via argv — the flag must survive that hop."""
    from unittest.mock import patch

    custom = tmp_path / "offsite" / "vectors.sqlite"
    with patch("doc_kg.mcp_server.main") as mock_main:
        CliRunner().invoke(cli, ["mcp", "--repo", str(tmp_path), "--vectors-path", str(custom)])

    assert mock_main.call_args is not None, "mcp_server.main was never called"
    argv = mock_main.call_args.kwargs["argv"]
    assert "--vectors-path" in argv
    assert argv[argv.index("--vectors-path") + 1] == str(custom)


# ---------------------------------------------------------------------------
# MCP server startup output
# ---------------------------------------------------------------------------


def _run_mcp_main(argv):
    """Drive mcp_server.main with only the transport stubbed; return stderr.

    ``DocKG`` is deliberately *not* stubbed: the banner reports the vector store
    the real instance resolves, so a mock would make these assertions vacuous.
    Construction is lazy — no model is loaded and no store is opened.
    """
    import io
    import sys as _sys
    from unittest.mock import patch

    import doc_kg.mcp_server as ms

    buf = io.StringIO()
    with patch.object(ms.mcp, "run"), patch.object(_sys, "stderr", buf):
        ms.main(argv=argv)
    return buf.getvalue()


def test_mcp_banner_uses_real_newlines(tmp_path):
    """The banner is built from escaped strings; a doubled backslash makes it
    print a literal \\n and collapse into one run-on line."""
    db = tmp_path / ".dockg" / "graph.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    out = _run_mcp_main(["--repo", str(tmp_path), "--db", str(db)])

    assert "\\n" not in out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0] == "DocKG MCP server starting"
    # Each field lands on its own line.
    for field in ("repo", "db", "backend", "vectors", "model", "transport"):
        assert any(ln.strip().startswith(field) for ln in lines), field


def test_mcp_missing_db_warning_uses_real_newline(tmp_path):
    out = _run_mcp_main(["--repo", str(tmp_path), "--db", "absent/graph.sqlite"])

    assert "\\n" not in out
    assert "WARNING: SQLite database not found" in out
    assert any(ln.strip() == "Run 'dockg build' first." for ln in out.splitlines())


def test_mcp_banner_reports_derived_vectors_path(tmp_path):
    """With no --vectors-path the banner must resolve the sidecar, not say "(derived)".

    Printing a placeholder — or the LanceDB directory, which is not written under
    the default backend — leaves the operator guessing which store is serving
    queries.
    """
    db = tmp_path / ".dockg" / "graph.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    out = _run_mcp_main(["--repo", str(tmp_path), "--db", str(db)])
    assert "backend  : sqlite-vec" in out
    assert f"vectors  : {tmp_path / '.dockg' / 'vectors.sqlite'}" in out
    assert "(derived)" not in out


def test_mcp_banner_honours_explicit_vectors_path(tmp_path):
    """An explicit --vectors-path is what the banner reports."""
    db = tmp_path / ".dockg" / "graph.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    custom = tmp_path / "elsewhere" / "vectors.sqlite"

    out = _run_mcp_main(["--repo", str(tmp_path), "--db", str(db), "--vectors-path", str(custom)])
    assert f"vectors  : {custom}" in out


# ---------------------------------------------------------------------------
# Help-text accuracy
# ---------------------------------------------------------------------------

# Wording that makes a LanceDB mention truthful: it marks the mention as the
# retired backend, a conversion source, or one choice among several.
_LANCEDB_QUALIFIERS = (
    "legacy",
    "pre-0.20.0",
    "ignored by sqlite-vec",
    "anchors",
    "source",
    "extra",
    "auto|lancedb|sqlite-vec",
)


def test_help_text_never_presents_lancedb_as_the_default_store():
    """No command may describe LanceDB as where vectors actually go.

    The 0.20.0 migration moved the default store to sqlite-vec but left the help
    strings behind, so ``dockg build --help`` advertised a backend the build no
    longer writes.  LanceDB may still be *mentioned* — it is a real legacy
    option — so this checks that every mention carries a qualifier rather than
    banning the word.  Help text is whitespace-normalised first because Click
    rewraps it, which would otherwise split a qualifier from its mention.
    """
    from click.testing import CliRunner

    from doc_kg.cli.main import cli

    runner = CliRunner()
    offenders = []
    for name in sorted(cli.commands):
        # convert-index reads a LanceDB store by definition.
        if name == "convert-index":
            continue
        text = " ".join(runner.invoke(cli, [name, "--help"]).output.split()).lower()
        start = 0
        while (hit := text.find("lancedb", start)) != -1:
            window = text[max(0, hit - 140) : hit + 140]
            if not any(q in window for q in _LANCEDB_QUALIFIERS):
                offenders.append(f"{name}: ...{window}...")
            start = hit + 1

    assert not offenders, "unqualified LanceDB claims in help text:\n" + "\n".join(offenders)


def test_build_help_names_the_store_it_writes():
    """The positive half: build must say what it actually indexes into."""
    from click.testing import CliRunner

    from doc_kg.cli.main import cli

    text = " ".join(CliRunner().invoke(cli, ["build", "--help"]).output.split()).lower()
    assert "sqlite-vec" in text
    assert "indexes it in lancedb" not in text
