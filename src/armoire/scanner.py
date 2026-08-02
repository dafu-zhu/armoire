"""One directory in, one listing out. Never recurses."""

import logging
from dataclasses import dataclass
from pathlib import Path

from armoire.ignore import is_ignored
from armoire.paths import resolve_in_root

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int
    mtime: float
    ext: str


def _sort_key(entry: Entry) -> tuple[str, str]:
    """Case-insensitive, with the exact name as tiebreaker.

    The secondary key matters: lower() alone ties for names differing only by
    case, and stability then falls through to iterdir()'s filesystem-defined
    order, which varies across runs and platforms.
    """
    return (entry.name.lower(), entry.name)


def _entry(path: Path) -> Entry | None:
    """Build an Entry, or None if the OS will not tell us about it."""
    try:
        stat = path.stat()
        is_dir = path.is_dir()
    except OSError as exc:
        # Permission denied, broken symlink, or a file that vanished mid-scan.
        # Skipping is correct: a folder the user cannot read is not browsable.
        # Logged so a systemic failure is not indistinguishable from an empty
        # directory.
        logger.debug("skipping %s: %s", path, exc)
        return None

    return Entry(
        name=path.name,
        is_dir=is_dir,
        size=0 if is_dir else stat.st_size,
        mtime=stat.st_mtime,
        ext="" if is_dir else path.suffix.removeprefix(".").lower(),
    )


def list_dir(root: Path, relative: str) -> tuple[list[Entry], list[Entry]]:
    """Return (dirs, files) for one directory, each sorted case-insensitively.

    Sorting uses _sort_key: case-insensitive primary key with exact name as
    tiebreaker. This ensures deterministic ordering across runs and platforms.
    """
    target = resolve_in_root(root, relative)
    if not target.is_dir():
        raise FileNotFoundError(relative)

    dirs: list[Entry] = []
    files: list[Entry] = []
    for child in target.iterdir():
        if is_ignored(child.name):
            continue
        entry = _entry(child)
        if entry is None:
            continue
        (dirs if entry.is_dir else files).append(entry)

    dirs.sort(key=_sort_key)
    files.sort(key=_sort_key)
    return dirs, files
