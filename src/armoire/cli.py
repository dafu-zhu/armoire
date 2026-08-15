"""Command line entry point."""

import os
import subprocess
import sys
import time
from pathlib import Path

import click
import uvicorn

from armoire import __version__, instance, startup, store
from armoire.app import create_app
from armoire.projects import REGISTRY_NAME

DEFAULT_PORT = 8420
# Budget for a detached child to bind and answer. Generous: a cold start on a
# large folder spends most of it building the file index.
DETACH_TIMEOUT = 10.0
DETACH_POLL = 0.1


class DashboardPortRace(Exception):
    """A dashboard-selected port changed owners before startup completed."""


def _same_folder(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


GROUP_EPILOG = """\
\b
Examples:
  armoire dashboard                   browse the current folder
  armoire list                        show every folder and URL
  armoire serve .                     advanced: serve in this terminal
  armoire serve ~/notes -d            run it in the background
  armoire serve ~/notes -df           replace the armoire already on that port
  armoire serve ~/notes -dp 9000      background, on port 9000
  armoire startup remove summer-26    remove a legacy logon registration

One process serves one folder, so several folders means several ports.
`armoire dashboard` assigns those ports automatically and never replaces anything.
"""

SERVE_EPILOG = """\
\b
Examples:
  armoire serve .
  armoire serve ~/notes -dp 9000
"""

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
# status = "not-started"           # not-started | active | paused | done
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


def _log_path(port: int) -> Path:
    """Where a detached server's output goes. One file per port, truncated per
    launch -- a log that grows forever is a log nobody opens."""
    return store.config_root() / f"serve-{port}.log"


def _spawn_detached(argv: list[str], log: Path | None) -> subprocess.Popen:
    """Start `argv` in its own session, outliving this process.

    `log` is None when armoire may not write for this folder, in which case
    the child's output goes to the null device: a convenience log does not get
    to break the promise that serving a folder never writes into it.
    """
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        extra = {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            "startupinfo": startupinfo,
        }
    else:
        extra = {"start_new_session": True}
    if log is None:
        return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, **extra)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT, **extra)


def serve_epilog() -> str:
    """The serve command's epilog, exposed so a test can assert on its copy."""
    return SERVE_EPILOG


@click.group(epilog=GROUP_EPILOG)
@click.version_option(__version__)
def main() -> None:
    """Serve any folder as a local, read-only website."""


@main.command(epilog=SERVE_EPILOG)
@click.argument(
    "folder",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option("--port", "-p", default=DEFAULT_PORT, show_default=True, help="Port to listen on.")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help=(
        "Replace an armoire already on this port. Does nothing when the port "
        "is free, and never stops a process armoire cannot identify as its own."
    ),
)
@click.option(
    "--detach",
    "-d",
    is_flag=True,
    help=(
        "Run in the background and hand back the prompt. Output goes to a log file in the store."
    ),
)
def serve(
    folder: Path,
    port: int,
    force: bool,
    detach: bool,
    quiet: bool = False,
) -> None:
    """Browse FOLDER at http://127.0.0.1:PORT. Never writes to FOLDER.

    armoire's registry and project statuses live in its own per-user store,
    outside the served folder, and that store is the only thing it writes.
    """
    root = folder.resolve()
    try:
        claim = instance.claim_port(port, force)
    except instance.PortBusy as busy:
        if quiet:
            if _same_folder(busy.instance.root, root):
                return
            raise DashboardPortRace(port) from None
        # The folder, not just the pid: replacing a stale server of your own
        # and destroying one you still wanted are the same keystrokes, and
        # only the folder name tells them apart.
        click.echo(
            f"armoire: port {port} is serving {busy.instance.root} (pid {busy.instance.pid})",
            err=True,
        )
        # -df first because it is the answer nearly every time: someone
        # blocked by a server they lost track of is about to make another one
        # they will also lose. Bare -f is never recommended -- replacing a
        # server and then holding the terminal open recreates the problem.
        click.echo("  -df replaces it and runs without keeping this terminal open", err=True)
        click.echo("  --force replaces it and stays in this terminal", err=True)
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None
    except instance.PortForeign:
        if quiet:
            raise DashboardPortRace(port) from None
        click.echo(
            f"armoire: port {port} is in use, and what holds it is not armoire",
            err=True,
        )
        # Spelled out because the other error has just recommended forcing.
        # Silence here would read as a bug rather than a refusal.
        click.echo(
            "  armoire stops only processes it can identify as its own, so --force will not help",
            err=True,
        )
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None
    except instance.PortStuck:
        if quiet:
            raise DashboardPortRace(port) from None
        click.echo(
            f"armoire: the armoire on port {port} was asked to stop but did not release the port",
            err=True,
        )
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None

    if not quiet:
        click.echo(f"armoire serving {root}")
        click.echo(f"  http://127.0.0.1:{port}")
    if claim.replaced_pid is not None and not quiet:
        click.echo(
            f"  replaced the armoire serving {claim.replaced_root} on {port} "
            f"(pid {claim.replaced_pid})"
        )
    for line in prepare_store(root):
        if not quiet:
            click.echo(line)
    if detach:
        # No --force in the child's argv: the parent already claimed the port,
        # so the child should find it free. If it does not, something raced --
        # and a child that force-kills whatever it finds would be stopping a
        # process nobody authorised it to touch. The poll below reports that
        # instead.
        log = None if store.writes_inside(root) else _log_path(port)
        _spawn_detached(
            [sys.executable, "-m", "armoire.cli", "serve", str(root), "--port", str(port)],
            log,
        )
        deadline = time.monotonic() + DETACH_TIMEOUT
        while time.monotonic() < deadline:
            found = instance.probe(port)
            if found is not None:
                if not _same_folder(found.root, root):
                    if quiet:
                        raise DashboardPortRace(port)
                    time.sleep(DETACH_POLL)
                    continue
                if quiet:
                    return
                click.echo(f"  running in the background (pid {found.pid})")
                if log is None:
                    click.echo("  no log: the armoire store is inside the served folder")
                else:
                    click.echo(f"  log {log}")
                return
            time.sleep(DETACH_POLL)
        # Never print a pid for a process that died on startup -- reporting a
        # success that is not one is the failure this whole feature exists to
        # stop.
        click.echo(
            f"armoire: the background server did not start within {DETACH_TIMEOUT:.0f}s",
            err=True,
        )
        if log is not None:
            click.echo(f"  see {log}", err=True)
        raise SystemExit(1)

    instance.record(port, root, os.getpid())
    try:
        # Loopback only, always. This streams arbitrary bytes out of the root.
        uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
    finally:
        # Ctrl-C and SIGTERM both land here. A record left behind would make
        # `list` probe a dead port -- harmless, since it prunes, but tidying
        # up on the way out costs one call.
        instance.forget(port)


@main.command()
@click.pass_context
def dashboard(ctx: click.Context) -> None:
    """Serve the current folder in the background and print its URL."""
    root = Path.cwd().resolve()
    for found in instance.running():
        if _same_folder(found.root, root):
            click.echo(root)
            click.echo(f"http://127.0.0.1:{found.port}")
            return
    start = DEFAULT_PORT
    while True:
        found, port = instance.matching_or_free_port(root, start)
        if found is not None:
            click.echo(root)
            click.echo(f"http://127.0.0.1:{found.port}")
            return
        assert port is not None
        try:
            ctx.invoke(
                serve,
                folder=root,
                port=port,
                force=False,
                detach=True,
                quiet=True,
            )
        except DashboardPortRace:
            start = port + 1
            continue
        click.echo(root)
        click.echo(f"http://127.0.0.1:{port}")
        return


@main.command("list")
def list_instances() -> None:
    """Show the armoire instances currently running.

    One process serves one folder, so several folders means several ports.
    This is the answer to "which port was that folder on".
    """
    live = instance.running()
    if not live:
        click.echo("no armoire instances running")
        return
    urls = [(f"http://127.0.0.1:{found.port}", found.root) for found in live]
    width = max(len("URL"), *(len(url) for url, _root in urls))
    click.echo(f"{'URL':<{width}}  FOLDER")
    for url, root in urls:
        click.echo(f"{url:<{width}}  {root}")
    click.echo()
    click.echo(f"{len(live)} running")


@main.group("startup")
def startup_group() -> None:
    """Remove legacy Windows-logon registrations."""


@startup_group.command("remove")
@click.argument("target")
def startup_remove(target: str) -> None:
    """Delete a legacy logon registration and stop its matching server."""
    try:
        removed = startup.remove(target)
    except (ValueError, startup.RemovalError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"startup disabled for {removed.folder} on port {removed.port}")


if __name__ == "__main__":
    main()
