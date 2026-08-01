"""The single gate for turning a request path into a filesystem path.

Every filesystem access in armoire goes through resolve_in_root. The server
streams arbitrary bytes from the root, so an escape here is the whole security
boundary failing.
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
