"""Where armoire keeps its own data.

The registry describes a folder; it does not belong inside it. Putting it in
the served folder made describing a folder require modifying it, which is the
one thing a read-only viewer promises not to do -- and it ruled out folders you
cannot or should not write to.

Everything armoire writes goes here and nowhere else.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

APP_NAME = "armoire"


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
    return folder_dir(folder) / "registry.toml"


def state_path(folder: Path) -> Path:
    return folder_dir(folder) / "state.json"


def store_is_inside(folder: Path) -> bool:
    """True when the store sits inside the folder being served.

    Serving a home directory would otherwise make every write land inside the
    tree armoire promises not to touch.
    """
    try:
        return Path(os.path.realpath(config_root())).is_relative_to(Path(os.path.realpath(folder)))
    except (OSError, ValueError):
        return False


def read_state(folder: Path) -> dict:
    """The stored state, or {} when absent, unreadable or malformed.

    A corrupt state file must not take the roadmap down: status is a
    convenience, and losing it is better than refusing to render.
    """
    try:
        parsed = json.loads(state_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # json.loads("[1,2]") succeeds and yields a list, which every caller would
    # then .get() against and crash on.
    return parsed if isinstance(parsed, dict) else {}


def write_state(folder: Path, state: dict) -> None:
    """Replace state.json atomically.

    Written to a temporary file in the same directory and renamed, so an
    interrupted write cannot leave a truncated file where a valid one was.
    os.replace is atomic on both POSIX and Windows.
    """
    target = state_path(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)
