"""Command line entry point."""

from pathlib import Path

import click
import uvicorn

from armoire import __version__
from armoire.app import create_app

DEFAULT_PORT = 8420


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Serve any folder as a local, read-only website."""


@main.command()
@click.argument(
    "folder",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option("--port", default=DEFAULT_PORT, show_default=True, help="Port to listen on.")
def serve(folder: Path, port: int) -> None:
    """Browse FOLDER at http://127.0.0.1:PORT. Never writes to disk."""
    root = folder.resolve()
    click.echo(f"armoire serving {root}")
    click.echo(f"  http://127.0.0.1:{port}")
    # Loopback only, always. This streams arbitrary bytes out of the root.
    uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
