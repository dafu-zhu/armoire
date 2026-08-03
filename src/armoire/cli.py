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

    Writing anything here would land inside the served tree when the write
    target is itself a descendant of the folder being served -- a home
    directory, %APPDATA% itself, or (per review) a folder inside the store's
    own "folders" tree. In that case armoire serves read-only and says so,
    rather than quietly breaking the one guarantee it makes. writes_inside
    asks exactly that question, about the write target rather than about
    config_root() as a whole; see its docstring for why the weaker question
    misses the descendant case.
    """
    if store.writes_inside(folder):
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
        # Bytes, not text: a decode-then-re-encode round trip raises
        # UnicodeDecodeError out of serve for a non-UTF-8 Phase 2 registry --
        # an unhandled traceback and no server at all, where the old
        # behaviour (registry read straight from the served folder) was a
        # server that started and showed a friendly RegistryError. It also
        # silently rewrites line endings. A raw byte copy defers that same
        # friendly error to load_registry, which already handles it, and
        # changes nothing else about the file's content.
        #
        # Not wrapped in try/except OSError: unlike store.read_state (which
        # swallows a bad read because status is a convenience and losing it
        # beats refusing to render), a failed migration here must not be
        # mistaken for "no legacy registry" -- that would silently start the
        # user on an empty stub while their real, unreadable project data
        # sits right next to it. Failing loudly is safer than losing it quietly.
        target.write_bytes(legacy.read_bytes())
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
    """Browse FOLDER at http://127.0.0.1:PORT. Never writes to FOLDER.

    armoire's registry and project statuses live in its own per-user store,
    outside the served folder, and that store is the only thing it writes.
    """
    root = folder.resolve()
    click.echo(f"armoire serving {root}")
    click.echo(f"  http://127.0.0.1:{port}")
    for line in prepare_store(root):
        click.echo(line)
    # Loopback only, always. This streams arbitrary bytes out of the root.
    uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
