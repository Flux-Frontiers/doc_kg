"""CLI smoke tests for Click command registration."""

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
