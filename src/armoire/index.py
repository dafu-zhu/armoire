"""A flat list of every non-ignored file, for the filter box.

Built once at startup on a background thread. The server serves requests while
the walk runs; the filter box reports "indexing" until it finishes.
"""

import logging
import os
import threading
from pathlib import Path

from armoire.ignore import is_ignored

logger = logging.getLogger(__name__)


def _on_walk_error(error: OSError) -> None:
    """os.walk swallows scandir errors by default, dropping whole subtrees silently."""
    logger.debug("skipping unreadable directory: %s", error)


def build_index(root: Path) -> list[str]:
    """Walk the tree once, pruning ignored directories before descending."""
    root = root.resolve()
    found: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_walk_error):
        # Mutating dirnames in place is what stops os.walk descending into
        # the ignored trees at all, rather than filtering them afterwards.
        dirnames[:] = [d for d in dirnames if not is_ignored(d)]
        base = Path(dirpath)
        for name in filenames:
            if is_ignored(name):
                continue
            found.append((base / name).relative_to(root).as_posix())

    found.sort()
    return found


class PathIndex:
    """Owns the background build and the result."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._paths: list[str] = []
        self._ready = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            paths = build_index(self._root)
        except Exception:
            # A stranded index is worse than an empty one: Task 7 serves
            # `ready` straight to clients, which would report "indexing"
            # forever with no error visible anywhere.
            logger.exception("index build failed for %s", self._root)
            paths = []
        self._paths = paths
        self._ready = True

    def wait(self, timeout: float | None = None) -> None:
        """Block until the build finishes. Used by tests and `armoire check`."""
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def paths(self) -> list[str]:
        return self._paths

    @property
    def ready(self) -> bool:
        return self._ready
