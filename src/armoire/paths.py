"""The single gate for turning a request path into a filesystem path.

Every *request-derived* path in armoire goes through resolve_in_root, which
also rejects a null byte in the path outright. `index.py`'s background walk
(os.walk, no request input, followlinks=False by default) and app.py's
StaticFiles mount (its own traversal check) are the two filesystem accesses
that do not go through it -- both are safe, but neither takes a request path
as input. The server streams arbitrary bytes from the root for anything that
does, so an escape here is the whole security boundary failing.
"""

from pathlib import Path


class PathOutsideRoot(Exception):
    """A request path resolved to somewhere outside the served root."""


def resolve_in_root(root: Path, relative: str) -> Path:
    """Resolve `relative` against `root`, refusing anything that escapes it.

    Resolution follows symlinks, so a symlink inside the root that points
    outside it is refused just like a `..` traversal.
    """
    if "\x00" in relative:
        raise PathOutsideRoot(relative)

    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()

    if not candidate.is_relative_to(resolved_root):
        raise PathOutsideRoot(relative)

    return candidate
