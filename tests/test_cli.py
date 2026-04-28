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
