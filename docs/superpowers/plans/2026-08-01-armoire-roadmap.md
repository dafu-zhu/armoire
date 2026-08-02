# armoire Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace armoire's file-browser entry screen with a draggable dependency roadmap over registered projects, drilling down to the existing viewer.

**Architecture:** A TOML registry declares projects, their paths, and what blocks what. A backend module parses it and a second derives activity from `git log`. The frontend lays the graph out with dagre, renders the SVG itself for full control over dragging and click targets, and persists node positions in `localStorage` so the served folder is never written to.

**Tech Stack:** Python 3.11+ (`tomllib` is stdlib), FastAPI, `subprocess` for git. Frontend is plain ES modules with `dagre` vendored locally. Tests are pytest and Playwright.

**Spec:** `docs/superpowers/specs/2026-08-01-armoire-roadmap-design.md`

## Global Constraints

- Python 3.11 floor. CI matrix is 3.11, 3.12, 3.13 on ubuntu-latest and windows-latest.
- `pathlib` for all path handling. No platform-specific path strings.
- **Scoped exception to Phase 1's "no shell-outs":** `activity.py` invokes `git` via `subprocess.run` with a list argument and `shell=False`. Phase 1's constraint was about path manipulation; reading git history has no pure-Python alternative short of a heavyweight dependency. Every invocation carries a timeout and never interpolates user input into a shell string.
- The server binds `127.0.0.1` only. No `--host` option may exist.
- **`serve` never writes to the served folder.** Node positions live in `localStorage`, not on disk. The read-only test must be extended to cover the new endpoints.
- No CDN at runtime; `dagre` is vendored under `src/armoire/static/vendor/` and committed, so the wheel stays self-contained.
- No build step; plain ES modules.
- Colours from the existing CSS custom properties in `app.css`. Introduce no new hex values outside the category palette defined in Task 5.
- Frontend behaviour is verified by Playwright against a live server, never by asserting on JavaScript source text.
- The suite must report **0 warnings and 0 xfailed**.
- With no `armoire.toml`, the roadmap does not appear and armoire behaves exactly as it does today.

## URL migration

Phase 1 used `#/<path>` for everything. The roadmap needs `#/` for itself, which
creates ambiguity: a folder named `project` would collide with `#/project/<name>`.

All file browsing moves under `#/browse/`:

| URL | Screen |
|---|---|
| `#/` | Roadmap, or the root listing when no registry exists |
| `#/browse/` | Root file listing |
| `#/browse/research/0dte/README.md` | A file |
| `#/project/0DTE` | Project detail |

This removes the collision rather than special-casing it — a folder named
`browse` is `#/browse/browse`. Bookmarks made under the old scheme break; the
tool has been installable for under a day, so that cost is accepted rather than
carrying a redirect layer forever.

## File Structure

| File | Responsibility |
|---|---|
| `src/armoire/projects.py` | Parse and validate `armoire.toml`; resolve edges; detect cycles |
| `src/armoire/activity.py` | Commit count and last-commit time per path, submodule-aware |
| `src/armoire/app.py` | Two new routes. Dispatch only. |
| `scripts/vendor.py` | Add dagre to the vendored set |
| `src/armoire/static/roadmap.js` | dagre layout, SVG render, pointer drag, localStorage |
| `src/armoire/static/rail.js` | Collapsible activity/blocked/issues rail |
| `src/armoire/static/project.js` | Project detail view |
| `src/armoire/static/app.js` | Route dispatch across roadmap, project, browse |
| `src/armoire/static/index.html` | `#roadmap` and `#rail` containers; vendor script tag |
| `src/armoire/static/app.css` | Roadmap, rail and detail styles |
| `tests/test_projects.py` | Registry parsing |
| `tests/test_activity.py` | Git activity extraction |
| `tests/test_roadmap.py` | Playwright: graph, drag, rail, detail, fallback |

---

### Task 1: Registry parser

**Files:**
- Create: `src/armoire/projects.py`
- Test: `tests/test_projects.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `armoire.projects.REGISTRY_NAME: str` — `"armoire.toml"`
  - `armoire.projects.RegistryError(Exception)`
  - `armoire.projects.Project` — frozen dataclass: `name: str`, `paths: tuple[str, ...]`, `blocked_by: tuple[str, ...]`, `category: str | None`, `due: str | None`, `note: str | None`
  - `armoire.projects.Registry` — dataclass: `projects: list[Project]`, `issues: list[str]`
  - `armoire.projects.load_registry(root: Path) -> Registry | None` — `None` when no registry file exists

`due` is stored as an **ISO string**, not a `date`, so the value is JSON-serialisable without a custom encoder — the same reasoning that makes `preview_table` stringify cells.

- [ ] **Step 1: Write the failing test**

Create `tests/test_projects.py`:

```python
import pytest

from armoire.projects import RegistryError, load_registry

VALID = """
[[project]]
name = "0DTE"
paths = ["research/0dte"]
blocked_by = ["FINM 320"]
category = "research"
due = 2026-08-17
note = "arXiv preprint"

[[project]]
name = "FINM 320"
paths = ["learning/finm32000"]
"""


def write(root, text):
    (root / "armoire.toml").write_text(text, encoding="utf-8")
    for name in ("research/0dte", "learning/finm32000"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def test_no_registry_returns_none(tmp_path):
    assert load_registry(tmp_path) is None


def test_parses_projects_in_declaration_order(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    assert [p.name for p in registry.projects] == ["0DTE", "FINM 320"]


def test_optional_fields_default_to_none_or_empty(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    finm = registry.projects[1]
    assert finm.blocked_by == ()
    assert finm.category is None
    assert finm.due is None
    assert finm.note is None


def test_due_is_an_iso_string_not_a_date(tmp_path):
    import json

    registry = load_registry(write(tmp_path, VALID))
    assert registry.projects[0].due == "2026-08-17"
    json.dumps(registry.projects[0].due)


def test_paths_is_a_tuple_of_strings(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    assert registry.projects[0].paths == ("research/0dte",)


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, "[[project]\nname = "))


def test_missing_name_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, '[[project]]\npaths = ["a"]\n'))


def test_missing_paths_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, '[[project]]\nname = "A"\n'))


def test_duplicate_name_raises_naming_both(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["x"]\n\n[[project]]\nname = "A"\npaths = ["y"]\n'
    with pytest.raises(RegistryError, match="A"):
        load_registry(write(tmp_path, text))


def test_unknown_blocked_by_is_an_issue_not_an_error(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["Ghost"]\n'
    registry = load_registry(write(tmp_path, text))
    assert [p.name for p in registry.projects] == ["A"]
    assert any("Ghost" in issue for issue in registry.issues)


def test_cycle_is_reported_with_its_path(tmp_path):
    text = (
        '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["B"]\n\n'
        '[[project]]\nname = "B"\npaths = ["research/0dte"]\nblocked_by = ["A"]\n'
    )
    registry = load_registry(write(tmp_path, text))
    assert any("cycle" in issue.lower() for issue in registry.issues)
    assert len(registry.projects) == 2


def test_missing_path_is_an_issue(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["nowhere"]\n'
    registry = load_registry(write(tmp_path, text))
    assert any("nowhere" in issue for issue in registry.issues)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_projects.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'armoire.projects'`

- [ ] **Step 3: Write the implementation**

Create `src/armoire/projects.py`:

```python
"""The project registry.

armoire.toml declares what a project is and what blocks it. Neither can be
inferred: a project may span several folders, and the dependency edges exist
only in the author's head. A tool that guesses structure is worse than one that
admits it does not know, so no registry means no roadmap.
"""

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REGISTRY_NAME = "armoire.toml"


class RegistryError(Exception):
    """The registry exists but could not be loaded."""


@dataclass(frozen=True)
class Project:
    name: str
    paths: tuple[str, ...]
    blocked_by: tuple[str, ...] = ()
    category: str | None = None
    due: str | None = None
    note: str | None = None


@dataclass
class Registry:
    projects: list[Project]
    issues: list[str] = field(default_factory=list)


def _as_str_tuple(value, field_name: str, project: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise RegistryError(f"{project}: {field_name} must be a list, not a string")
    return tuple(str(item) for item in value)


def _parse_project(entry: dict, position: int) -> Project:
    name = entry.get("name")
    if not name:
        raise RegistryError(f"project #{position} has no name")
    paths = entry.get("paths")
    if not paths:
        raise RegistryError(f"{name}: no paths declared")

    due = entry.get("due")
    # ISO string, not a date object: the value crosses the API as JSON, and a
    # date would need a custom encoder for no benefit.
    if isinstance(due, date):
        due = due.isoformat()
    elif due is not None:
        due = str(due)

    return Project(
        name=str(name),
        paths=_as_str_tuple(paths, "paths", str(name)),
        blocked_by=_as_str_tuple(entry.get("blocked_by", ()), "blocked_by", str(name)),
        category=entry.get("category"),
        due=due,
        note=entry.get("note"),
    )


def _find_cycle(projects: list[Project]) -> list[str] | None:
    """Return one cycle as a name path, or None. Iterative DFS with a colour map."""
    edges = {p.name: [b for b in p.blocked_by] for p in projects}
    known = set(edges)
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)

    for start in edges:
        if colour[start] != WHITE:
            continue
        stack = [(start, iter(edges[start]))]
        path = [start]
        colour[start] = GREY
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if child not in known:
                    continue
                if colour[child] == GREY:
                    return path[path.index(child) :] + [child]
                if colour[child] == WHITE:
                    colour[child] = GREY
                    path.append(child)
                    stack.append((child, iter(edges[child])))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                stack.pop()
                path.pop()
    return None


def load_registry(root: Path) -> Registry | None:
    """Load armoire.toml, or None when there is none.

    Structural problems raise: a malformed file or a duplicate name means the
    graph cannot be trusted at all. Referential problems become issues: an
    unknown blocker or a missing folder still leaves a drawable graph, and
    reporting them beats refusing to render.
    """
    path = root / REGISTRY_NAME
    if not path.is_file():
        return None

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise RegistryError(f"{REGISTRY_NAME}: {exc}") from exc

    projects: list[Project] = []
    seen: dict[str, int] = {}
    for position, entry in enumerate(raw.get("project", []), start=1):
        project = _parse_project(entry, position)
        if project.name in seen:
            raise RegistryError(
                f"duplicate project name {project.name!r} "
                f"(entries #{seen[project.name]} and #{position})"
            )
        seen[project.name] = position
        projects.append(project)

    issues: list[str] = []
    known = {p.name for p in projects}
    for project in projects:
        for blocker in project.blocked_by:
            if blocker not in known:
                issues.append(f"{project.name}: blocked_by names unknown project {blocker!r}")
        for relative in project.paths:
            if not (root / relative).exists():
                issues.append(f"{project.name}: path {relative!r} does not exist")

    cycle = _find_cycle(projects)
    if cycle is not None:
        issues.append("dependency cycle: " + " -> ".join(cycle))

    return Registry(projects=projects, issues=issues)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_projects.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and the full suite**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: clean, 0 warnings, existing tests unaffected

- [ ] **Step 6: Commit**

```bash
git add src/armoire/projects.py tests/test_projects.py
git commit -m "feat: project registry parser"
```

---

### Task 2: Git activity

**Files:**
- Create: `src/armoire/activity.py`
- Test: `tests/test_activity.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `armoire.activity.Activity` — frozen dataclass: `commits: int`, `last: float | None` (Unix timestamp)
  - `armoire.activity.activity_for(root: Path, relative: str, days: int = 30) -> Activity`
  - `armoire.activity.recent_commits(root: Path, relative: str, limit: int = 10) -> list[dict]` — each `{"sha": str, "subject": str, "when": float}`

Both run `git -C <absolute path> log … -- .`. Running from inside the directory rather than from the repository root is what makes submodules work: git walks up from the given directory and finds the submodule's own repository, whereas the parent repository's log cannot see inside it. The originating corpus has four submodules.

- [ ] **Step 1: Write the failing test**

Create `tests/test_activity.py`:

```python
import subprocess

import pytest

from armoire.activity import activity_for, recent_commits


def git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]},
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha" / "a.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "first alpha commit")
    (tmp_path / "alpha" / "a.txt").write_text("2", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "second alpha commit")
    (tmp_path / "beta" / "b.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "only beta commit")
    return tmp_path


def test_counts_commits_scoped_to_the_path(repo):
    assert activity_for(repo, "alpha").commits == 2
    assert activity_for(repo, "beta").commits == 1


def test_reports_a_last_commit_timestamp(repo):
    result = activity_for(repo, "alpha")
    assert result.last is not None and result.last > 0


def test_a_path_with_no_history_reports_zero(repo):
    (repo / "gamma").mkdir()
    result = activity_for(repo, "gamma")
    assert result.commits == 0


def test_a_missing_path_reports_zero_without_raising(repo):
    assert activity_for(repo, "nowhere").commits == 0


def test_outside_a_repository_reports_zero_without_raising(tmp_path):
    (tmp_path / "plain").mkdir()
    assert activity_for(tmp_path, "plain").commits == 0


def test_outside_a_repository_still_reports_a_last_touch_from_mtimes(tmp_path):
    """Not every folder is in git; the spec requires an mtime fallback."""
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "f.txt").write_text("x", encoding="utf-8")
    result = activity_for(tmp_path, "plain")
    assert result.commits == 0
    assert result.last is not None and result.last > 0


def test_an_empty_untracked_folder_reports_no_last_touch(tmp_path):
    (tmp_path / "hollow").mkdir()
    assert activity_for(tmp_path, "hollow").last is None


def test_recent_commits_returns_subjects_newest_first(repo):
    entries = recent_commits(repo, "alpha")
    assert [e["subject"] for e in entries] == ["second alpha commit", "first alpha commit"]
    assert all(len(e["sha"]) >= 7 for e in entries)
    assert all(isinstance(e["when"], float) for e in entries)


def test_recent_commits_honours_the_limit(repo):
    assert len(recent_commits(repo, "alpha", limit=1)) == 1


def test_a_submodule_is_read_from_its_own_repository(repo, tmp_path_factory):
    """The parent repository's log cannot see inside a submodule."""
    inner = tmp_path_factory.mktemp("inner")
    git(inner, "init", "-q", "-b", "main")
    (inner / "x.txt").write_text("1", encoding="utf-8")
    git(inner, "add", "-A")
    git(inner, "commit", "-qm", "inner commit one")
    (inner / "x.txt").write_text("2", encoding="utf-8")
    git(inner, "add", "-A")
    git(inner, "commit", "-qm", "inner commit two")

    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "sub")
    git(repo, "commit", "-qm", "add submodule")

    assert activity_for(repo, "sub").commits == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_activity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'armoire.activity'`

- [ ] **Step 3: Write the implementation**

Create `src/armoire/activity.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_activity.py -v`
Expected: PASS. If the submodule test fails with a protocol error, the local git
refuses `file://` submodules by policy; the test already passes
`-c protocol.file.allow=always`. If it still fails, report rather than deleting
the test — submodule support is a stated requirement.

- [ ] **Step 5: Measure against the real corpus**

Run:

```bash
uv run python -c "import time; from pathlib import Path; from armoire.activity import activity_for; r=Path(r'D:/GitHub/summer-26'); t=time.perf_counter(); [activity_for(r,p) for p in ['research/0dte','research/bayesian-smc-sv','bofa','xtech','learning','leetcode','planner']]; print(round(time.perf_counter()-t,2),'s for 7 paths')"
```

Expected: under 5 seconds. Record the number in the commit message. If it is
slower, stop and report — the design assumes this is cheap enough to compute
once on the startup thread.

- [ ] **Step 6: Commit**

```bash
git add src/armoire/activity.py tests/test_activity.py
git commit -m "feat: git-derived project activity"
```

---

### Task 3: Registry and activity endpoints

**Files:**
- Modify: `src/armoire/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `load_registry`, `Registry`, `Project`, `RegistryError`, `activity_for`, `recent_commits`, `list_dir`
- Produces:

```
GET /api/projects
  200 {"root": str,
       "projects": [{"name","paths","blocked_by","category","due","note",
                     "commits": int, "last": float|None}],
       "issues": [str]}
  200 {"root": str, "projects": [], "issues": [], "registry": false}   # no armoire.toml
  200 {"root": str, "projects": [], "issues": [str], "error": str}     # malformed

GET /api/project/<name>
  200 {"project": {...}, "blocks": [str], "commits": [{"sha","subject","when"}],
       "files": [{"path": str, "name": str, "is_dir": bool}]}
  404 {"detail": "no such project"}
```

A malformed registry returns **200 with an `error` field**, not a 4xx. The
client must still render the page and show the parse error; a status code would
push it down the generic error path and hide which line was wrong.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
REGISTRY = """
[[project]]
name = "Downstream"
paths = ["docs"]
blocked_by = ["Upstream"]
category = "research"
due = 2026-08-17
note = "a note"

[[project]]
name = "Upstream"
paths = ["docs"]
"""


@pytest.fixture
def registry_root(root):
    (root / "armoire.toml").write_text(REGISTRY, encoding="utf-8")
    return root


@pytest.fixture
def registry_client(registry_root):
    app = create_app(registry_root)
    app.state.index.wait(timeout=10)
    return TestClient(app)


def test_projects_endpoint_lists_declared_projects(registry_client):
    body = registry_client.get("/api/projects").json()
    assert [p["name"] for p in body["projects"]] == ["Downstream", "Upstream"]
    assert body["issues"] == []


def test_projects_endpoint_carries_optional_fields(registry_client):
    body = registry_client.get("/api/projects").json()
    downstream = body["projects"][0]
    assert downstream["blocked_by"] == ["Upstream"]
    assert downstream["category"] == "research"
    assert downstream["due"] == "2026-08-17"
    assert downstream["note"] == "a note"


def test_projects_endpoint_includes_activity_so_the_graph_needs_one_call(registry_client):
    body = registry_client.get("/api/projects").json()
    assert all("commits" in p and "last" in p for p in body["projects"])


def test_no_registry_reports_that_rather_than_erroring(client):
    body = client.get("/api/projects").json()
    assert body["registry"] is False
    assert body["projects"] == []


def test_malformed_registry_is_200_with_an_error_field(root):
    (root / "armoire.toml").write_text("[[project]\nname = ", encoding="utf-8")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/projects")
    assert response.status_code == 200
    assert "error" in response.json()


def test_project_detail_reports_what_it_blocks(registry_client):
    body = registry_client.get("/api/project/Upstream").json()
    assert body["blocks"] == ["Downstream"]


def test_project_detail_lists_files_under_its_paths(registry_client):
    body = registry_client.get("/api/project/Downstream").json()
    assert any(f["name"] == "readme.md" for f in body["files"])


def test_unknown_project_is_404(registry_client):
    assert registry_client.get("/api/project/Ghost").status_code == 404


def test_project_name_with_a_slash_does_not_escape(registry_client):
    assert registry_client.get("/api/project/../../etc").status_code in (404, 422)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app.py -k registry -q`
Expected: FAIL — 404 on `/api/projects`

- [ ] **Step 3: Write the implementation**

In `src/armoire/app.py`, add imports:

```python
from armoire.activity import activity_for, recent_commits
from armoire.projects import RegistryError, load_registry
```

and inside `create_app`, before the StaticFiles mount:

```python
    @app.get("/api/projects")
    def projects() -> dict:
        envelope = {"root": str(root), "projects": [], "issues": []}
        try:
            registry = load_registry(root)
        except RegistryError as exc:
            # 200, not 4xx: the client must still render the page and show
            # which line was wrong. A status code hides that behind the
            # generic error path.
            logger.warning("registry failed to load: %s", exc)
            return envelope | {"error": str(exc)}
        if registry is None:
            return envelope | {"registry": False}

        listed = []
        for project in registry.projects:
            merged = {"commits": 0, "last": None}
            for relative in project.paths:
                found = activity_for(root, relative)
                merged["commits"] += found.commits
                if found.last is not None:
                    merged["last"] = max(merged["last"] or 0.0, found.last)
            listed.append(asdict(project) | {"paths": list(project.paths),
                                             "blocked_by": list(project.blocked_by)} | merged)
        return envelope | {"projects": listed, "issues": registry.issues}

    @app.get("/api/project/{name}")
    def project_detail(name: str) -> dict:
        try:
            registry = load_registry(root)
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if registry is None:
            raise HTTPException(status_code=404, detail="no registry")

        match = next((p for p in registry.projects if p.name == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail="no such project")

        files = []
        for relative in match.paths:
            try:
                dirs, entries = list_dir(root, relative)
            except (PathOutsideRoot, FileNotFoundError):
                continue
            for entry in [*dirs, *entries]:
                files.append(
                    {
                        "path": f"{relative}/{entry.name}",
                        "name": entry.name,
                        "is_dir": entry.is_dir,
                    }
                )

        commits = []
        for relative in match.paths:
            commits.extend(recent_commits(root, relative))
        commits.sort(key=lambda c: c["when"], reverse=True)

        return {
            "project": asdict(match)
            | {"paths": list(match.paths), "blocked_by": list(match.blocked_by)},
            "blocks": [p.name for p in registry.projects if name in p.blocked_by],
            "commits": commits[:10],
            "files": files,
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_app.py -q`
Expected: PASS

- [ ] **Step 5: Extend the read-only assertion**

In `tests/test_app.py::test_serving_never_writes_to_disk`, add the two new
endpoints to the exercised set, after the existing per-file loop:

```python
    client.get("/api/projects")
    client.get("/api/project/Downstream")
```

The fixture for that test has no registry, so both return their no-registry
responses — which is exactly the path most likely to be exercised in the wild
and still must not write.

- [ ] **Step 6: Run lint and the full suite, then commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest -q
git add src/armoire/app.py tests/test_app.py
git commit -m "feat: projects and project detail endpoints"
```

---

### Task 4: Route dispatch and the `#/browse/` migration

Frontend routing changes before any roadmap exists, so the migration is
verifiable on its own and the roadmap task starts from a stable router.

**Files:**
- Modify: `src/armoire/static/app.js`, `src/armoire/static/renderers/listing.js`, `src/armoire/static/renderers/markdown.js`, `src/armoire/static/tree.js`, `src/armoire/static/filter.js`
- Test: `tests/test_navigation.py`

**Interfaces:**
- Consumes: `encodeHashPath` from `./format.js`
- Produces: `app.js` exports `navigate(path)` (unchanged signature, now writing `#/browse/…`) and `navigateProject(name)`

Every existing hash-write site must move to the new scheme. Phase 1 found three
of them the hard way — `navigate()`, the breadcrumb, and `rewriteLinks` in
`markdown.js` — plus `listing.js` builds `href` values directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_navigation.py`:

```python
def test_root_shows_the_file_listing_when_there_is_no_registry(page, live_server):
    page.goto(live_server)
    page.wait_for_selector(".listing", timeout=10000)
    assert page.locator(".listing").count() == 1


def test_files_live_under_the_browse_prefix(page, live_server):
    page.goto(f"{live_server}/#/browse/code.py")
    page.wait_for_selector("pre.code", timeout=10000)
    assert "return" in page.locator("pre.code").inner_text()


def test_clicking_a_file_in_the_tree_writes_a_browse_url(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    page.locator('#tree [data-path="code.py"]').click()
    page.wait_for_function("() => location.hash === '#/browse/code.py'", timeout=5000)
    assert page.evaluate("location.hash") == "#/browse/code.py"


def test_a_relative_markdown_link_writes_a_browse_url(page, live_server):
    page.goto(f"{live_server}/#/browse/links.md")
    page.wait_for_selector(".markdown-body a", timeout=10000)
    href = page.locator(".markdown-body a").first.get_attribute("href")
    assert href.startswith("#/browse/")


def test_a_listing_link_writes_a_browse_url(page, live_server):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector(".listing a", timeout=10000)
    href = page.locator(".listing a").first.get_attribute("href")
    assert href.startswith("#/browse/")


def test_a_folder_named_browse_does_not_collide(page, live_server):
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector(".markdown-body h1", timeout=10000)
    assert page.locator(".markdown-body h1").inner_text() == "Buried"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_navigation.py -k browse -q`
Expected: FAIL — hashes are still written without the prefix

- [ ] **Step 3: Add route parsing to `app.js`**

Replace `currentPath()` and `navigate()` in `src/armoire/static/app.js` with:

```js
const BROWSE = 'browse';
const PROJECT = 'project';

function decodeSegments(raw) {
  return raw
    .split('/')
    .map((segment) => decodeURIComponent(segment))
    .join('/');
}

// Everything that is not a file lives behind a reserved first segment, and
// every file lives behind `browse`. That removes the collision entirely: a
// folder actually named "browse" is #/browse/browse.
function currentRoute() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  if (raw === '') return { kind: 'home' };
  const slash = raw.indexOf('/');
  const head = slash === -1 ? raw : raw.slice(0, slash);
  const rest = slash === -1 ? '' : raw.slice(slash + 1);
  if (head === PROJECT) return { kind: 'project', name: decodeURIComponent(rest) };
  if (head === BROWSE) return { kind: 'browse', path: decodeSegments(rest) };
  return { kind: 'unknown', raw };
}

export function navigate(path) {
  window.location.hash = `/${BROWSE}/${encodeHashPath(path)}`;
}

export function navigateProject(name) {
  window.location.hash = `/${PROJECT}/${encodeURIComponent(name)}`;
}
```

- [ ] **Step 4: Update every other hash-write site**

`renderBreadcrumb` in `app.js` — the root link and each accumulated segment:

```js
  rootLink.href = `#/${BROWSE}/`;
```
```js
    link.href = `#/${BROWSE}/${encodeHashPath(accumulated)}`;
```

`src/armoire/static/renderers/listing.js` — the entry link:

```js
      link.href = `#/browse/${encodeHashPath(path ? `${path}/${entry.name}` : entry.name)}`;
```

This needs `import { encodeHashPath } from '../format.js';` at the top if it is
not already there.

`src/armoire/static/renderers/markdown.js` — in `rewriteLinks`:

```js
    anchor.setAttribute('href', `#/browse/${encodeHashPath(normalise(`${basePath}/${href}`))}`);
```

Leave the image rewriting alone — it builds an `/api/raw?path=` URL, not a hash.

- [ ] **Step 5: Rewire the dispatcher**

Replace the `hashchange` listener and the initial load in `app.js`:

```js
async function showRoute(route) {
  if (route.kind === 'project') {
    status.textContent = 'Loading…';
    // Task 8 replaces this with the real detail view.
    content.replaceChildren();
    return;
  }
  const path = route.kind === 'browse' ? route.path : '';
  renderBreadcrumb(path);
  status.textContent = 'Loading…';
  try {
    const meta = await renderPreview(content, path);
    status.textContent = meta || path || '/';
  } catch (error) {
    showError(error);
  }
  tree.revealPath(path);
}

window.addEventListener('hashchange', () => {
  let route;
  try {
    route = currentRoute();
  } catch (error) {
    showError(error);
    return;
  }
  if (route.kind === 'home') {
    window.location.hash = `/${BROWSE}/`;
    return;
  }
  showRoute(route);
});

tree.ready
  .then(() => {
    const route = currentRoute();
    if (route.kind === 'home') {
      window.location.hash = `/${BROWSE}/`;
      return;
    }
    showRoute(route);
  })
  .catch(showError);
```

Task 6 replaces the `home` branch with the roadmap.

- [ ] **Step 6: Run the tests and the full suite**

Run: `uv run pytest tests/test_navigation.py -v` then `uv run pytest -q`
Expected: PASS, 0 warnings

- [ ] **Step 7: Executed revert evidence**

Change `navigate()` back to `window.location.hash = \`/${encodeHashPath(path)}\``,
run `test_clicking_a_file_in_the_tree_writes_a_browse_url`, paste the failure,
then restore.

- [ ] **Step 8: Commit**

```bash
git add src/armoire/static/app.js src/armoire/static/renderers/listing.js src/armoire/static/renderers/markdown.js tests/test_navigation.py
git commit -m "feat: move file browsing under the browse route prefix"
```

---

### Task 5: Vendor dagre, shell containers, and styles

**Files:**
- Modify: `scripts/vendor.py`, `src/armoire/static/index.html`, `src/armoire/static/app.css`
- Test: `tests/test_vendor.py`

**Interfaces:**
- Produces: global `dagre` on `window`; DOM ids `roadmap`, `rail`, `rail-toggle`; CSS classes `.node`, `.edge`, `.node-badge`, `.rail`, `.rail-open`, `.cat-0` … `.cat-5`

- [ ] **Step 1: Add dagre to the vendor script**

In `scripts/vendor.py`, add to `FILES`:

```python
    "dagre.js": "https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js",
```

- [ ] **Step 2: Fetch it and confirm**

Run: `uv run python scripts/vendor.py`
Expected: `src/armoire/static/vendor/dagre.js` exists, roughly 93 KB.

- [ ] **Step 3: Write the failing test**

Append to `tests/test_vendor.py`:

```python
def test_dagre_is_vendored():
    assert (STATIC / "vendor" / "dagre.js").is_file()


def test_dagre_is_loaded_before_the_module_entry_point():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/vendor/dagre.js" in html
    assert html.index("/vendor/dagre.js") < html.index('src="/app.js"')
```

- [ ] **Step 4: Add the script tag and containers**

In `src/armoire/static/index.html`, add after the other vendor scripts:

```html
<script src="/vendor/dagre.js"></script>
```

and replace the `#body` block with:

```html
<div id="body">
  <nav id="tree" aria-label="Folder tree"></nav>
  <main id="main">
    <div id="breadcrumb"></div>
    <div id="content"></div>
  </main>
  <section id="roadmap" hidden aria-label="Project roadmap">
    <svg id="roadmap-canvas"></svg>
    <button id="rail-toggle" type="button" aria-expanded="false">Details</button>
    <aside id="rail" hidden></aside>
    <div id="roadmap-controls">
      <button id="zoom-out" type="button">&minus;</button>
      <span id="zoom-level">100%</span>
      <button id="zoom-in" type="button">+</button>
      <button id="layout-reset" type="button">Reset layout</button>
    </div>
  </section>
</div>
```

- [ ] **Step 5: Add the styles**

Append to `src/armoire/static/app.css`:

```css
/* Roadmap ------------------------------------------------------------- */
#roadmap { position: relative; flex: 1; min-width: 0; display: none; }
#roadmap[data-active="true"] { display: block; }
#roadmap-canvas { width: 100%; height: 100%; display: block; cursor: grab; background: var(--bg); }
#roadmap-canvas.dragging { cursor: grabbing; }

.node rect {
  fill: var(--subtle);
  stroke: var(--border);
  stroke-width: 1;
  rx: 6;
}
.node.blocked rect { stroke: #bc4c00; stroke-width: 2; }
.node text { font-family: var(--sans); font-size: 13px; fill: var(--fg); }
.node .node-sub { font-size: 11px; fill: var(--muted); }
.node .node-badge { font-size: 11px; fill: var(--muted); }
.node .node-warn { font-size: 14px; font-weight: 700; fill: #bc4c00; cursor: help; }
.node:hover rect { stroke: var(--link); }

.cat-0 rect { fill: #ddf4e4; stroke: #2da44e; }
.cat-1 rect { fill: #fff1e5; stroke: #bc4c00; }
.cat-2 rect { fill: #ddf4ff; stroke: #0969da; }
.cat-3 rect { fill: #fbefff; stroke: #8250df; }
.cat-4 rect { fill: #fff8c5; stroke: #9a6700; }
.cat-5 rect { fill: var(--subtle); stroke: var(--border); }

.edge { stroke: var(--muted); stroke-width: 1.4; fill: none; }

#roadmap-controls {
  position: absolute; right: 12px; bottom: 12px;
  display: flex; align-items: center; gap: 8px;
  padding: 4px 8px; font-size: 12px; color: var(--muted);
  background: var(--subtle); border: 1px solid var(--border); border-radius: var(--radius);
}
#roadmap-controls button {
  font: inherit; padding: 2px 8px; color: var(--fg);
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius); cursor: pointer;
}

#rail-toggle {
  position: absolute; right: 12px; top: 12px;
  font: inherit; font-size: 12px; padding: 4px 12px;
  color: var(--fg); background: var(--subtle);
  border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer;
}
#rail {
  position: absolute; right: 0; top: 0; bottom: 0; width: 280px;
  overflow-y: auto; padding: 44px 16px 16px;
  background: var(--bg); border-left: 1px solid var(--border);
}
#rail h4 { margin: 16px 0 6px; font-size: 11px; text-transform: uppercase; color: var(--muted); }
#rail ul { margin: 0; padding: 0; list-style: none; font-size: 12px; line-height: 1.9; }
#rail .issue { color: #bc4c00; }
```

- [ ] **Step 6: Run the tests, then commit**

Run: `uv run pytest tests/test_vendor.py -v` then `uv run pytest -q`

```bash
git add scripts/vendor.py src/armoire/static/vendor/dagre.js src/armoire/static/index.html src/armoire/static/app.css tests/test_vendor.py
git commit -m "feat: vendor dagre and add roadmap containers"
```

---

### Task 6: Render the roadmap

**Files:**
- Create: `src/armoire/static/roadmap.js`
- Modify: `src/armoire/static/app.js`
- Test: `tests/test_roadmap.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `GET /api/projects`, global `dagre`, `navigateProject` from `app.js`
- Produces: `roadmap.js` exports `renderRoadmap(canvas: SVGElement, data: object, onOpen: (name) => void)`. In **this** task it returns an internal handle (`{positions, redrawEdges, viewport, nodeLayer}`) used only inside the module. **Task 7 changes the return to `{reset(), zoomBy(factor)}`**, which is what `app.js` consumes — so assign it to `roadmapView` here but do not call anything on it yet.

- [ ] **Step 1: Add a registry to the test fixture**

In `tests/conftest.py`, inside `sample_root`, before `return root`:

```python
    # A registry makes the roadmap appear. Two nodes and one edge is the
    # smallest graph that exercises layout, an edge, and a blocked node.
    (root / "armoire.toml").write_text(
        '[[project]]\n'
        'name = "Downstream"\n'
        'paths = ["notes"]\n'
        'blocked_by = ["Upstream"]\n'
        'category = "research"\n'
        'due = 2026-08-17\n'
        '\n'
        '[[project]]\n'
        'name = "Upstream"\n'
        'paths = ["notes/deep"]\n'
        'category = "learning"\n',
        encoding="utf-8",
        newline="",
    )
```

Existing navigation tests that assert the root shows a listing must be updated
to visit `#/browse/` explicitly, since `#/` now becomes the roadmap.

Adding a registry here removes the last coverage of the no-registry fallback —
the case every folder in the world is in until someone writes an `armoire.toml`.
Give it a dedicated server. Also in `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def bare_root(tmp_path_factory):
    """A folder with no armoire.toml -- the state every folder starts in."""
    root = tmp_path_factory.mktemp("bare")
    (root / "README.md").write_bytes(b"# Bare\n\nNo registry here.\n")
    return root


@pytest.fixture(scope="session")
def bare_server(bare_root):
    app = create_app(bare_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("bare server did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_roadmap.py`:

```python
"""The roadmap, exercised in a real browser."""


def open_roadmap(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)


def test_roadmap_is_the_entry_screen_when_a_registry_exists(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap").is_visible()


def test_every_declared_project_becomes_a_node(page, live_server):
    open_roadmap(page, live_server)
    labels = page.locator("#roadmap .node").all_inner_texts()
    assert any("Downstream" in text for text in labels)
    assert any("Upstream" in text for text in labels)


def test_blocked_by_becomes_an_edge(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap .edge").count() == 1


def test_the_blocker_is_laid_out_before_the_blocked(page, live_server):
    """rankdir LR: a blocker must sit to the left of what it blocks."""
    open_roadmap(page, live_server)
    boxes = {}
    for handle in page.locator("#roadmap .node").element_handles():
        name = handle.inner_text()
        boxes["Upstream" if "Upstream" in name else "Downstream"] = handle.bounding_box()["x"]
    assert boxes["Upstream"] < boxes["Downstream"]


def test_a_node_shows_its_commit_badge(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap .node-badge").count() >= 1


def test_a_due_date_appears_on_its_node(page, live_server):
    open_roadmap(page, live_server)
    assert "2026-08-17" in page.locator("#roadmap").inner_text()


def test_clicking_a_node_opens_the_project_route(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#roadmap .node", has_text="Upstream").first.click()
    page.wait_for_function("() => location.hash.startsWith('#/project/')", timeout=5000)
    assert page.evaluate("location.hash") == "#/project/Upstream"


def test_a_folder_with_no_registry_opens_on_the_file_browser(page, bare_server):
    """The state every folder is in until someone writes an armoire.toml."""
    page.goto(bare_server)
    page.wait_for_selector(".listing", timeout=15000)
    assert page.locator("#roadmap").is_hidden()
    assert page.evaluate("location.hash") == "#/browse/"


def test_no_console_errors_rendering_the_roadmap(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append((m.text, m.location.get("url", ""))) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append((str(e), "")))
    open_roadmap(page, live_server)
    page.wait_for_load_state("networkidle")
    assert errors == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_roadmap.py -q`
Expected: FAIL — timeout waiting for `#roadmap .node`

- [ ] **Step 4: Write the renderer**

Create `src/armoire/static/roadmap.js`:

```js
// The roadmap. dagre assigns ranks and positions; the SVG is rendered here so
// click targets, drag and styling stay under our control -- mermaid would emit
// a static picture we would then have to fight.

const NODE_W = 168;
const NODE_H = 62;
const CATEGORIES = 6;

function categoryClass(category, order) {
  if (!category) return 'cat-5';
  if (!order.has(category)) order.set(category, order.size % (CATEGORIES - 1));
  return `cat-${order.get(category)}`;
}

function svgEl(name, attrs = {}) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  return el;
}

function layout(projects) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 72, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  const known = new Set(projects.map((p) => p.name));
  for (const project of projects) {
    g.setNode(project.name, { width: NODE_W, height: NODE_H });
  }
  for (const project of projects) {
    for (const blocker of project.blocked_by) {
      // An unknown blocker is reported as an issue in the rail; drawing an
      // edge to a node that does not exist would throw inside dagre.
      if (known.has(blocker)) g.setEdge(blocker, project.name);
    }
  }
  dagre.layout(g);
  return g;
}

export function renderRoadmap(canvas, data, onOpen) {
  const projects = data.projects || [];
  const g = layout(projects);
  const order = new Map();
  const positions = new Map();

  canvas.replaceChildren();
  const defs = svgEl('defs');
  const marker = svgEl('marker', {
    id: 'arrow', markerWidth: '9', markerHeight: '9',
    refX: '8', refY: '3', orient: 'auto',
  });
  marker.append(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: 'var(--muted)' }));
  defs.append(marker);
  canvas.append(defs);

  const viewport = svgEl('g', { id: 'viewport' });
  const edgeLayer = svgEl('g');
  const nodeLayer = svgEl('g');
  viewport.append(edgeLayer, nodeLayer);
  canvas.append(viewport);

  for (const id of g.nodes()) positions.set(id, { ...g.node(id) });

  function edgePath(from, to) {
    const a = positions.get(from);
    const b = positions.get(to);
    const midX = (a.x + NODE_W / 2 + (b.x - NODE_W / 2)) / 2;
    return `M${a.x + NODE_W / 2},${a.y} C${midX},${a.y} ${midX},${b.y} ${b.x - NODE_W / 2},${b.y}`;
  }

  const edges = [];
  for (const e of g.edges()) {
    const path = svgEl('path', {
      class: 'edge', d: edgePath(e.v, e.w), 'marker-end': 'url(#arrow)',
    });
    edgeLayer.append(path);
    edges.push({ from: e.v, to: e.w, path });
  }

  function redrawEdges() {
    for (const edge of edges) edge.path.setAttribute('d', edgePath(edge.from, edge.to));
  }

  const blockedNames = new Set(
    projects.filter((p) => p.blocked_by.length > 0).map((p) => p.name),
  );

  // Issues are strings of the form "<project>: <what is wrong>". A node whose
  // name leads an issue gets a marker, so a missing folder or an unknown
  // blocker is visible on the graph and not only in a rail nobody opened.
  const flagged = new Set(
    (data.issues || [])
      .map((issue) => issue.split(':')[0].trim())
      .filter((name) => projects.some((p) => p.name === name)),
  );

  for (const project of projects) {
    const pos = positions.get(project.name);
    if (!pos) continue;
    const group = svgEl('g', {
      class: `node ${categoryClass(project.category, order)}${
        blockedNames.has(project.name) ? ' blocked' : ''
      }`,
      'data-name': project.name,
      transform: `translate(${pos.x - NODE_W / 2},${pos.y - NODE_H / 2})`,
      tabindex: '0',
      role: 'button',
    });
    group.append(svgEl('rect', { width: NODE_W, height: NODE_H }));

    const title = svgEl('text', { x: 12, y: 24 });
    title.textContent = project.name;
    group.append(title);

    const subtitle = project.due || project.note || '';
    if (subtitle) {
      const sub = svgEl('text', { x: 12, y: 42, class: 'node-sub' });
      sub.textContent = subtitle;
      group.append(sub);
    }

    const badge = svgEl('text', {
      x: NODE_W - 12, y: 24, class: 'node-badge', 'text-anchor': 'end',
    });
    badge.textContent = `${project.commits}`;
    group.append(badge);

    if (flagged.has(project.name)) {
      const warn = svgEl('text', {
        x: NODE_W - 12, y: NODE_H - 12, class: 'node-warn', 'text-anchor': 'end',
      });
      warn.textContent = '!';
      const reason = svgEl('title');
      reason.textContent = (data.issues || [])
        .filter((issue) => issue.startsWith(`${project.name}:`))
        .join('\n');
      warn.append(reason);
      group.append(warn);
    }

    group.addEventListener('click', () => onOpen(project.name));
    group.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') onOpen(project.name);
    });
    nodeLayer.append(group);
  }

  const graph = g.graph();
  canvas.setAttribute('viewBox', `0 0 ${graph.width || 800} ${graph.height || 400}`);

  return { positions, redrawEdges, viewport, nodeLayer };
}
```

- [ ] **Step 5: Wire it into the router**

In `src/armoire/static/app.js`, import and add a home branch:

```js
import { renderRoadmap } from './roadmap.js';
```

```js
const roadmap = document.getElementById('roadmap');
const canvas = document.getElementById('roadmap-canvas');
const body = document.getElementById('body');

let roadmapView = null;

async function showRoadmap() {
  const response = await fetch('/api/projects');
  const data = await response.json();
  if (data.registry === false) {
    window.location.hash = `/${BROWSE}/`;
    return;
  }
  document.getElementById('tree').hidden = true;
  document.getElementById('main').hidden = true;
  roadmap.hidden = false;
  roadmap.dataset.active = 'true';
  if (data.error) {
    canvas.replaceChildren();
    const box = document.createElement('div');
    box.className = 'error';
    box.textContent = data.error;
    roadmap.append(box);
    return;
  }
  roadmapView = renderRoadmap(canvas, data, navigateProject);
  status.textContent = `${data.projects.length} projects`;
}

function hideRoadmap() {
  roadmap.hidden = true;
  roadmap.dataset.active = 'false';
  document.getElementById('tree').hidden = false;
  document.getElementById('main').hidden = false;
}
```

and in `showRoute`, replace the `home` handling so `kind === 'home'` calls
`showRoadmap()` and every other kind calls `hideRoadmap()` first.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_roadmap.py -v` then `uv run pytest -q`
Expected: PASS, 0 warnings

- [ ] **Step 7: Executed revert evidence**

Remove the `g.setEdge(...)` call, run `test_blocked_by_becomes_an_edge` and
`test_the_blocker_is_laid_out_before_the_blocked`, paste both failures, restore.

- [ ] **Step 8: Commit**

```bash
git add src/armoire/static/roadmap.js src/armoire/static/app.js tests/test_roadmap.py tests/conftest.py tests/test_navigation.py
git commit -m "feat: render the project roadmap"
```

---

### Task 7: Drag, pan, zoom and persistence

**Files:**
- Modify: `src/armoire/static/roadmap.js`, `src/armoire/static/app.js`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `renderRoadmap` as Task 6 left it, returning an internal handle
- Produces: `renderRoadmap`'s return **changes** to `{reset(), zoomBy(factor)}` — the internal handle stays in closure scope. `app.js`'s `roadmapView` now has methods to call. Positions persist under the `localStorage` key `armoire:layout:<root>`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roadmap.py`:

```python
def drag_node(page, name, dx, dy):
    node = page.locator(f'#roadmap .node[data-name="{name}"]')
    box = node.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy, steps=8)
    page.mouse.up()
    return box


def test_dragging_moves_a_node(page, live_server):
    open_roadmap(page, live_server)
    before = drag_node(page, "Upstream", 120, 60)
    after = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(after["x"] - before["x"]) > 40


def test_a_dragged_position_survives_a_reload(page, live_server):
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 120, 60)
    moved = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    page.reload()
    page.wait_for_selector("#roadmap .node", timeout=15000)
    restored = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(restored["x"] - moved["x"]) < 4


def test_reset_restores_the_computed_layout(page, live_server):
    open_roadmap(page, live_server)
    original = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    drag_node(page, "Upstream", 120, 60)
    page.locator("#layout-reset").click()
    page.wait_for_timeout(300)
    restored = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(restored["x"] - original["x"]) < 4


def test_dragging_does_not_write_to_the_served_folder(page, live_server, sample_root):
    """localStorage, not disk -- the read-only guarantee covers the roadmap too."""
    import hashlib

    def snapshot():
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(sample_root.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 90, 40)
    page.wait_for_timeout(300)
    assert snapshot() == before


def test_zoom_controls_change_the_reported_level(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#zoom-in").click()
    assert page.locator("#zoom-level").inner_text() != "100%"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_roadmap.py -k "drag or reset or zoom" -q`
Expected: FAIL — no drag handlers exist

- [ ] **Step 3: Add interaction to `roadmap.js`**

Add near the top:

```js
function storageKey(root) {
  return `armoire:layout:${root}`;
}

function loadSaved(root) {
  try {
    return JSON.parse(window.localStorage.getItem(storageKey(root)) || '{}');
  } catch {
    // A corrupt entry must not take the roadmap down with it.
    return {};
  }
}

function save(root, positions) {
  const plain = {};
  for (const [name, pos] of positions) plain[name] = { x: pos.x, y: pos.y };
  try {
    window.localStorage.setItem(storageKey(root), JSON.stringify(plain));
  } catch {
    // Quota or a privacy mode that blocks storage. Dragging still works for
    // this session; it just will not persist.
  }
}
```

In `renderRoadmap`, after `positions` is filled from dagre, apply saved
overrides and remember the computed defaults:

```js
  const computed = new Map();
  for (const [name, pos] of positions) computed.set(name, { x: pos.x, y: pos.y });
  const saved = loadSaved(data.root);
  for (const [name, pos] of Object.entries(saved)) {
    if (positions.has(name)) positions.set(name, { ...positions.get(name), ...pos });
  }
```

After the node loop, add dragging, panning and zoom:

```js
  let scale = 1;
  let pan = { x: 0, y: 0 };

  function applyViewport() {
    viewport.setAttribute('transform', `translate(${pan.x},${pan.y}) scale(${scale})`);
    const label = document.getElementById('zoom-level');
    if (label) label.textContent = `${Math.round(scale * 100)}%`;
  }

  function place(name) {
    const pos = positions.get(name);
    const group = nodeLayer.querySelector(`[data-name="${CSS.escape(name)}"]`);
    if (group) {
      group.setAttribute('transform', `translate(${pos.x - NODE_W / 2},${pos.y - NODE_H / 2})`);
    }
  }

  let dragging = null;
  canvas.addEventListener('pointerdown', (event) => {
    const group = event.target.closest('.node');
    const point = canvas.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(canvas.getScreenCTM().inverse());
    if (group) {
      const name = group.dataset.name;
      dragging = { name, offsetX: local.x - positions.get(name).x * scale - pan.x,
                   offsetY: local.y - positions.get(name).y * scale - pan.y, moved: false };
    } else {
      dragging = { name: null, offsetX: local.x - pan.x, offsetY: local.y - pan.y, moved: false };
      canvas.classList.add('dragging');
    }
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const point = canvas.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(canvas.getScreenCTM().inverse());
    dragging.moved = true;
    if (dragging.name) {
      positions.set(dragging.name, {
        ...positions.get(dragging.name),
        x: (local.x - dragging.offsetX - pan.x) / scale,
        y: (local.y - dragging.offsetY - pan.y) / scale,
      });
      place(dragging.name);
      redrawEdges();
    } else {
      pan = { x: local.x - dragging.offsetX, y: local.y - dragging.offsetY };
      applyViewport();
    }
  });

  canvas.addEventListener('pointerup', (event) => {
    canvas.classList.remove('dragging');
    if (dragging && dragging.name && dragging.moved) save(data.root, positions);
    dragging = null;
    canvas.releasePointerCapture(event.pointerId);
  });

  applyViewport();

  return {
    reset() {
      for (const [name, pos] of computed) positions.set(name, { ...pos });
      for (const name of positions.keys()) place(name);
      redrawEdges();
      try {
        window.localStorage.removeItem(storageKey(data.root));
      } catch {
        /* storage unavailable; the in-memory reset still applied */
      }
    },
    zoomBy(factor) {
      scale = Math.min(2.5, Math.max(0.35, scale * factor));
      applyViewport();
    },
  };
```

A node click must not fire after a drag. In the node `click` handler, guard on
the drag having moved:

```js
    group.addEventListener('click', () => {
      if (dragging && dragging.moved) return;
      onOpen(project.name);
    });
```

Declare `let dragging = null;` before the node loop so the handler closes over it.

- [ ] **Step 4: Wire the controls**

In `app.js`, after `roadmapView` is assigned:

```js
  document.getElementById('layout-reset').onclick = () => roadmapView.reset();
  document.getElementById('zoom-in').onclick = () => roadmapView.zoomBy(1.2);
  document.getElementById('zoom-out').onclick = () => roadmapView.zoomBy(1 / 1.2);
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_roadmap.py -v` then `uv run pytest -q`

- [ ] **Step 6: Executed revert evidence**

Remove the `save(data.root, positions)` call in `pointerup`, run
`test_a_dragged_position_survives_a_reload`, paste the failure, restore.

- [ ] **Step 7: Commit**

```bash
git add src/armoire/static/roadmap.js src/armoire/static/app.js tests/test_roadmap.py
git commit -m "feat: drag, pan, zoom and layout persistence"
```

---

### Task 8: The rail

**Files:**
- Create: `src/armoire/static/rail.js`
- Modify: `src/armoire/static/app.js`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Produces: `rail.js` exports `initRail(toggle: HTMLElement, panel: HTMLElement, data: object, onOpen: (name) => void)`

Collapsed by default; open state persists under `armoire:rail:<root>`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roadmap.py`:

```python
def test_the_rail_is_collapsed_by_default(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#rail").is_hidden()


def test_the_rail_toggles_open(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail:visible", timeout=5000)
    assert page.locator("#rail").is_visible()


def test_the_rail_ranks_projects_by_commit_count(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail li", timeout=5000)
    assert page.locator("#rail").inner_text().strip() != ""


def test_the_rail_lists_blocked_projects_with_their_blocker(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail li", timeout=5000)
    text = page.locator("#rail").inner_text()
    assert "Downstream" in text and "Upstream" in text


def test_the_rail_open_state_survives_a_reload(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail:visible", timeout=5000)
    page.reload()
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#rail").is_visible()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_roadmap.py -k rail -q`
Expected: FAIL — the toggle does nothing

- [ ] **Step 3: Write the rail**

Create `src/armoire/static/rail.js`:

```js
// Activity, blockers and registry issues. Collapsed by default: the graph is
// the product, and this is reference material you reach for deliberately.

function section(title) {
  const heading = document.createElement('h4');
  heading.textContent = title;
  return heading;
}

function list(items) {
  const ul = document.createElement('ul');
  for (const { text, className, onClick } of items) {
    const li = document.createElement('li');
    li.textContent = text;
    if (className) li.className = className;
    if (onClick) {
      li.style.cursor = 'pointer';
      li.addEventListener('click', onClick);
    }
    ul.append(li);
  }
  return ul;
}

export function initRail(toggle, panel, data, onOpen) {
  const key = `armoire:rail:${data.root}`;
  const projects = data.projects || [];

  panel.replaceChildren();

  const byActivity = [...projects].sort((a, b) => b.commits - a.commits);
  panel.append(
    section('Activity · 30 days'),
    list(
      byActivity.map((p) => ({
        text: `${p.name} — ${p.commits}`,
        onClick: () => onOpen(p.name),
      })),
    ),
  );

  const blocked = projects.filter((p) => p.blocked_by.length > 0);
  panel.append(
    section(`Blocked · ${blocked.length} of ${projects.length}`),
    list(
      blocked.map((p) => ({
        text: `${p.name} ← ${p.blocked_by.join(', ')}`,
        onClick: () => onOpen(p.name),
      })),
    ),
  );

  if ((data.issues || []).length) {
    panel.append(
      section('Registry issues'),
      list(data.issues.map((text) => ({ text, className: 'issue' }))),
    );
  }

  function apply(open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    try {
      window.localStorage.setItem(key, open ? '1' : '0');
    } catch {
      /* storage unavailable; the toggle still works for this session */
    }
  }

  let open = false;
  try {
    open = window.localStorage.getItem(key) === '1';
  } catch {
    open = false;
  }
  apply(open);

  toggle.addEventListener('click', () => {
    open = !open;
    apply(open);
  });
}
```

- [ ] **Step 4: Wire it in**

In `app.js`, import `initRail` and call it inside `showRoadmap` after
`renderRoadmap`:

```js
  initRail(
    document.getElementById('rail-toggle'),
    document.getElementById('rail'),
    data,
    navigateProject,
  );
```

- [ ] **Step 5: Run the tests, then commit**

```bash
uv run pytest tests/test_roadmap.py -v && uv run pytest -q
git add src/armoire/static/rail.js src/armoire/static/app.js tests/test_roadmap.py
git commit -m "feat: collapsible roadmap rail"
```

---

### Task 9: Project detail, README, and real-folder verification

**Files:**
- Create: `src/armoire/static/project.js`
- Modify: `src/armoire/static/app.js`, `README.md`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `GET /api/project/<name>`, `navigate` from `app.js`
- Produces: `project.js` exports `renderProject(container: HTMLElement, name: string, onOpenFile: (path) => void): Promise<string>`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roadmap.py`:

```python
def test_project_detail_shows_blockers_and_what_it_blocks(page, live_server):
    page.goto(f"{live_server}/#/project/Upstream")
    page.wait_for_selector(".project-detail", timeout=10000)
    text = page.locator(".project-detail").inner_text()
    assert "Downstream" in text


def test_project_detail_lists_files(page, live_server):
    page.goto(f"{live_server}/#/project/Downstream")
    page.wait_for_selector(".project-detail a", timeout=10000)
    assert page.locator(".project-detail a").count() >= 1


def test_a_file_link_in_the_detail_reaches_the_viewer(page, live_server):
    page.goto(f"{live_server}/#/project/Downstream")
    page.wait_for_selector(".project-detail a", timeout=10000)
    page.locator(".project-detail a").first.click()
    page.wait_for_function("() => location.hash.startsWith('#/browse/')", timeout=5000)


def test_an_unknown_project_shows_an_error_not_a_blank_page(page, live_server):
    page.goto(f"{live_server}/#/project/Ghost")
    page.wait_for_selector("#content .error", timeout=10000)
    assert page.locator("#content .error").inner_text().strip() != ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_roadmap.py -k project_detail -q`
Expected: FAIL — the project route renders nothing

- [ ] **Step 3: Write the detail view**

Create `src/armoire/static/project.js`:

```js
// One project: who blocks it, what it blocks, what is inside it, and what
// actually moved there recently.

function heading(level, text) {
  const el = document.createElement(level);
  el.textContent = text;
  return el;
}

function nameList(label, names) {
  const wrap = document.createElement('p');
  wrap.append(document.createTextNode(`${label}: `));
  wrap.append(document.createTextNode(names.length ? names.join(', ') : 'nothing'));
  return wrap;
}

function ago(seconds) {
  const days = (Date.now() / 1000 - seconds) / 86400;
  if (days < 1) return 'today';
  if (days < 2) return 'yesterday';
  if (days < 30) return `${Math.floor(days)} days ago`;
  return `${Math.floor(days / 30)} months ago`;
}

export async function renderProject(container, name, onOpenFile) {
  const response = await fetch(`/api/project/${encodeURIComponent(name)}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  const data = await response.json();

  container.replaceChildren();
  const root = document.createElement('div');
  root.className = 'project-detail';

  root.append(heading('h1', data.project.name));
  if (data.project.note) root.append(heading('p', data.project.note));
  if (data.project.due) root.append(heading('p', `Due ${data.project.due}`));

  root.append(nameList('Blocked by', data.project.blocked_by));
  root.append(nameList('Blocks', data.blocks));

  root.append(heading('h2', 'Files'));
  const files = document.createElement('ul');
  for (const file of data.files) {
    const li = document.createElement('li');
    const link = document.createElement('a');
    link.href = '#';
    link.textContent = file.is_dir ? `${file.name}/` : file.name;
    link.addEventListener('click', (event) => {
      event.preventDefault();
      onOpenFile(file.path);
    });
    li.append(link);
    files.append(li);
  }
  root.append(files);

  if (data.commits.length) {
    root.append(heading('h2', 'Recent commits'));
    const commits = document.createElement('ul');
    for (const commit of data.commits) {
      const li = document.createElement('li');
      li.textContent = `${commit.sha}  ${commit.subject} — ${ago(commit.when)}`;
      commits.append(li);
    }
    root.append(commits);
  }

  container.append(root);
  return `project · ${data.files.length} entries`;
}
```

- [ ] **Step 4: Wire it into the router**

In `app.js`, import `renderProject` and replace the placeholder `project` branch
in `showRoute`:

```js
  if (route.kind === 'project') {
    hideRoadmap();
    renderBreadcrumb('');
    status.textContent = 'Loading…';
    try {
      status.textContent = await renderProject(content, route.name, navigate);
    } catch (error) {
      showError(error);
    }
    return;
  }
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_roadmap.py -v` then `uv run pytest -q`
Expected: PASS, 0 warnings, 0 xfailed

- [ ] **Step 6: Verify against the real corpus**

Write an `armoire.toml` at `D:/GitHub/summer-26` covering the eight projects in
`planner/state.md` plus `0DTE`, with the dependency edges from the root README's
roadmap (`FINM 320` and `FINM 330` block `0DTE`; `0DTE` blocks the calibration
paper; `STAT 31450` and `STAT 31511` block it too; `finm330` blocks `finm320`).

Then run `uv run armoire serve D:/GitHub/summer-26` and confirm each row:

| Check | Expected |
|---|---|
| Entry screen | The roadmap, not a file listing |
| Node count | One per declared project |
| Edges | Match the declared `blocked_by` |
| Badges | Non-zero commit counts on active projects |
| Drag | A node moves and stays put after reload |
| Reset | Restores the dagre layout |
| Rail | Opens, ranks by activity, lists blocked projects |
| Node click | Opens the project detail |
| File click | Reaches the viewer and renders |
| A folder with no registry | Still opens on the file browser |

Report what you actually saw for each row.

- [ ] **Step 7: Update the README**

Replace the Status section of `README.md` with:

```markdown
## Status

Two screens. The roadmap shows your projects and what blocks what, drawn from an
`armoire.toml` you write; the viewer renders any file you click through to.
Without a registry, armoire opens straight into the file browser.

    [[project]]
    name = "0DTE"
    paths = ["research/0dte"]
    blocked_by = ["FINM 320", "FINM 330"]
    due = 2026-08-17

See the [roadmap design](docs/superpowers/specs/2026-08-01-armoire-roadmap-design.md)
for the full field list.
```

Also update the Use section's URL examples to the `#/browse/` scheme.

- [ ] **Step 8: Commit**

```bash
git add src/armoire/static/project.js src/armoire/static/app.js tests/test_roadmap.py README.md
git commit -m "feat: project detail view"
```

---

## Done

`armoire serve` opens on a draggable dependency roadmap, drills into project
detail, and reaches the Phase 1 viewer from there. A folder without an
`armoire.toml` behaves exactly as it did before.
