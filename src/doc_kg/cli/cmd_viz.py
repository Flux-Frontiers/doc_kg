"""
cmd_viz.py

Click subcommand for launching the DocKG visualizer:

  viz  — Streamlit-based interactive document graph explorer
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import click

from doc_kg.cli.main import cli

_VIZ_EXTRA = 'pip install "doc-kg[viz]"'


@cli.command("viz")
@click.option(
    "--db",
    default=".dockg/graph.sqlite",
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--port",
    default="8500",
    show_default=True,
    help="Streamlit server port.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Do not open a browser window automatically.",
)
def viz(db: str, port: str, no_browser: bool) -> None:
    """Launch the DocKG Streamlit visualizer."""
    if importlib.util.find_spec("streamlit") is None:
        raise click.UsageError(
            f"streamlit is not installed. Install viz dependencies with:\n  {_VIZ_EXTRA}"
        )

    app_path = Path(__file__).parent.parent / "app.py"
    if not app_path.exists():
        click.echo(f"ERROR: Could not find app.py at {app_path}", err=True)
        raise SystemExit(1)

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--",
        "--db",
        db,
    ]
    if no_browser:
        cmd[5:5] = ["--server.headless", "true"]

    click.echo(f"Launching DocKG Explorer on http://localhost:{port}")
    click.echo(f"  app   : {app_path}")
    click.echo(f"  db    : {db}")
    click.echo("  Press Ctrl+C to stop.\n")

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        click.echo("\nStopped.")
