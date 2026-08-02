"""Command line entry point."""

from pathlib import Path

import click
import uvicorn

from armoire import __version__, store
from armoire.app import create_app
from armoire.projects import REGISTRY_NAME

DEFAULT_PORT = 8420

STUB = """\
# armoire registry.
#
# This file lives outside the folder it describes, so describing a folder
# never modifies it.
#
# [[project]]
# name = "My project"
# paths = ["some/folder"]          # relative to the served folder
# blocked_by = ["Another project"] # optional
# category = "research"            # required when blocked_by is absent
# status = "active"                # not-started | active | paused | done
# note = "One line about it."
"""


def prepare_store(folder: Path) -> list[str]:
    """Ensure the store exists for this folder. Returns lines to print.

    Writing anything here would land inside the served tree when the store is
    a descendant of it -- a home directory, or %APPDATA% itself. In that case
    armoire serves read-only and says so, rather than quietly breaking the one
    guarantee it makes.
    """
    if store.store_is_inside(folder):
        return [
            f"  the armoire store is inside {folder} - serving read-only",
            "  status edits and registry creation are disabled here",
        ]

    target = store.registry_path(folder)
    if target.is_file():
        return [f"  registry {target}"]

    legacy = folder / REGISTRY_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if legacy.is_file():
        # Copied, not moved: deleting it would be a write to the served folder.
        target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        return [
            f"  migrated {legacy} into the store",
            f"  {target} is now authoritative; the copy in the folder is ignored",
        ]

    target.write_text(STUB, encoding="utf-8")
    return [f"  no registry yet - created {target}", "  edit it and reload to see the roadmap"]


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
    for line in prepare_store(root):
        click.echo(line)
    # Loopback only, always. This streams arbitrary bytes out of the root.
    uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
