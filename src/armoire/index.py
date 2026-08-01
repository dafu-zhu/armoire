"""A flat list of every non-ignored file, for the filter box.

Built once at startup on a background thread. The server serves requests while
the walk runs; the filter box reports "indexing" until it finishes.
"""

import os
import threading
from pathlib import Path

from armoire.ignore import is_ignored


def build_index(root: Path) -> list[str]:
    """Walk the tree once, pruning ignored directories before descending."""
    root = root.resolve()
    found: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
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
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        paths = build_index(self._root)
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
