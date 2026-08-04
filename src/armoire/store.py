"""Where armoire keeps its own data.

The registry describes a folder; it does not belong inside it. Putting it in
the served folder made describing a folder require modifying it, which is the
one thing a read-only viewer promises not to do -- and it ruled out folders you
cannot or should not write to.

Everything armoire writes goes here and nowhere else.
"""

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "armoire"
# The two files a folder's store directory holds. Named here rather than
# spelled inline at each use, so a caller that has already resolved
# folder_dir() once (app.create_app does, at creation time) can derive both
# paths from that single value instead of re-entering config_root().
REGISTRY_FILE = "registry.toml"
STATE_FILE = "state.json"


def _home() -> Path:
    # Indirected so the tests can point it somewhere without touching HOME,
    # which git and other subprocesses in the same session also read.
    return Path.home()


def config_root() -> Path:
    """The platform's user-config directory for armoire."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        # APPDATA is normally set, but a service account or a stripped
        # environment can lack it, and Path("") resolves to the process CWD --
        # which would put the store inside whatever folder we happen to serve.
        return (Path(base) if base else _home() / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else _home() / ".config") / APP_NAME


def _canonical(folder: Path) -> str:
    # normcase for Windows, where two spellings of one path differ only in case
    # and must not get two directories. realpath so a symlink and its target
    # resolve together.
    return os.path.normcase(os.path.realpath(folder))


def folder_key(folder: Path) -> str:
    """A stable, filesystem-safe directory name for a served folder.

    The tail is for a human reading the store; the hash is what makes it
    unique. Two folders with the same basename must not collide.
    """
    canonical = _canonical(folder)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    tail = "".join(c if c.isalnum() or c in "-_" else "-" for c in Path(canonical).name)
    tail = tail.strip("-")
    return f"{tail}-{digest}" if tail else digest


def folder_dir(folder: Path) -> Path:
    return config_root() / "folders" / folder_key(folder)


def registry_path(folder: Path) -> Path:
    return folder_dir(folder) / REGISTRY_FILE


def state_path(folder: Path) -> Path:
    return folder_dir(folder) / STATE_FILE


def writes_inside(folder: Path) -> bool:
    """True when the files armoire writes for `folder` land inside `folder`.

    The subject of the question is the *write target* -- folder_dir(folder),
    the per-folder directory keyed by folder's own hash -- and not
    config_root(). The obvious alternative, "does config_root() sit inside
    folder", is a strictly weaker question and gets the dangerous case wrong:
    when folder is a *descendant* of config_root() (serving config_root()
    itself, or its own "folders" tree), config_root() is not inside folder --
    it is the other way around -- and yet folder_dir(folder) still lands
    under folder, so the write armoire is about to make would go straight
    into the tree it promises not to touch. Asking about the target catches
    that; it also still catches the case that motivated the check in the
    first place, serving a home directory, since folder_dir(folder) sits
    under config_root() and therefore under folder too.
    """
    try:
        return Path(os.path.realpath(folder_dir(folder))).is_relative_to(
            Path(os.path.realpath(folder))
        )
    except (OSError, ValueError):
        return False


def read_state(state_file: Path) -> dict:
    """The state in `state_file`, or {} when absent, unreadable or malformed.

    Takes the file, not the folder it describes: the caller that knows which
    folder is being served resolves the path once (see app.create_app) rather
    than making every read re-enter config_root().

    A corrupt state file must not take the roadmap down: status is a
    convenience, and losing it is better than refusing to render.
    """
    try:
        parsed = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # json.loads("[1,2]") succeeds and yields a list, which every caller would
    # then .get() against and crash on.
    return parsed if isinstance(parsed, dict) else {}


def write_state(state_file: Path, state: dict) -> None:
    """Replace `state_file` atomically.

    Written to a temporary file in the same directory and renamed, so an
    interrupted write cannot leave a truncated file where a valid one was.
    os.replace is atomic on both POSIX and Windows.

    The temporary name comes from tempfile.mkstemp, so it is unique per
    writer. A fixed name (state.json.tmp) is not: it lives in a directory
    keyed only by the served folder, so two writers for one folder share it.
    Both open it, the later content overwrites the earlier, the first
    os.replace moves the file away, and the second raises FileNotFoundError
    -- a 500 for the second writer, with the file that did land carrying the
    *other* writer's state. FastAPI runs this module's `def` handlers in a
    threadpool, so two overlapping PUTs really are two parallel threads here.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=state_file.parent, prefix=f"{state_file.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(state, indent=2, sort_keys=True))
        os.replace(temporary, state_file)
    except BaseException:
        # The rename is what publishes the write, and it consumes the
        # temporary file. Anything that fails before it must take its own
        # temporary with it, or a directory that used to hold exactly
        # state.json accumulates one orphan per failed attempt.
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def open_in_editor(path: Path) -> None:
    """Hand `path` to whatever the OS has registered for it. Never waits.

    A GUI editor outlives the request that launched it, so nothing here
    waits on the child: Popen is started and abandoned. Waiting would pin
    the handler thread for as long as the user keeps the file open.

    os.startfile is looked up on `os` at call time rather than imported at
    module scope, because it exists only on Windows -- a module-level
    `from os import startfile` would make this whole module unimportable on
    Linux and macOS.

    The default verb, not "edit": `edit` is frequently unregistered for
    .toml and raises where the default verb succeeds.

    Failures raise OSError (FileNotFoundError for a missing xdg-open,
    OSError for a Windows association failure). The caller translates.
    """
    if sys.platform == "win32":
        os.startfile(path)
        return
    launcher = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([launcher, str(path)])
