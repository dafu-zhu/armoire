"""What actually moved, from git.

Every ledger records what was intended; none records what happened. This module
is the only part of armoire that shells out, and it does so with a list argument
and shell=False -- Phase 1's no-shell-outs rule was about path manipulation, and
reading git history has no pure-Python alternative short of a heavy dependency.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Activity:
    commits: int
    last: float | None


def _run(directory: Path, args: list[str]) -> str | None:
    """Run git in `directory`, or None if that is not possible.

    Running from inside the directory rather than from the served root is what
    makes submodules work: git walks up and finds the submodule's own
    repository. The parent repository's log cannot see inside it.
    """
    if not directory.is_dir():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # git missing, or a repository so large the log times out. Activity is
        # a nice-to-have; the roadmap must still render without it.
        logger.debug("git failed in %s: %s", directory, exc)
        return None
    if completed.returncode != 0:
        logger.debug("git exited %s in %s", completed.returncode, directory)
        return None
    return completed.stdout


def _newest_mtime(directory: Path) -> float | None:
    """Fallback for folders outside git. Bounded so a huge tree cannot stall."""
    newest: float | None = None
    seen = 0
    for path in directory.rglob("*"):
        if seen >= 2000:
            break
        try:
            if not path.is_file():
                continue
            stamp = path.stat().st_mtime
        except OSError:
            continue
        seen += 1
        if newest is None or stamp > newest:
            newest = stamp
    return newest


def activity_for(root: Path, relative: str, days: int = 30) -> Activity:
    directory = root / relative
    out = _run(directory, ["log", f"--since={days}.days", "--format=%ct", "--", "."])
    stamps = [float(line) for line in (out or "").split() if line.strip()]
    if stamps:
        return Activity(commits=len(stamps), last=max(stamps))
    # No git history, or no repository at all. A commit count of zero is
    # honest, but "last touched" is still knowable from the filesystem, and a
    # folder outside git would otherwise look permanently dead.
    return Activity(commits=0, last=_newest_mtime(directory))


def recent_commits(root: Path, relative: str, limit: int = 10) -> list[dict]:
    directory = root / relative
    out = _run(
        directory,
        ["log", f"-{limit}", "--format=%h%x1f%s%x1f%ct", "--", "."],
    )
    if not out:
        return []
    entries = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, subject, when = line.split("\x1f")
        entries.append({"sha": sha, "subject": subject, "when": float(when)})
    return entries
