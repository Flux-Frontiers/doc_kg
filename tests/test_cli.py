"""CLI smoke tests for Click command registration."""

from click.testing import CliRunner

from doc_kg.cli.main import cli


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
