# armoire Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the registry out of the served folder into a per-user store, add editable project status, and fix the roadmap and browse-pane defects the first real use exposed.

**Architecture:** A new `store.py` owns the platform config directory and every write armoire makes. `projects.py` loads from a path handed to it rather than finding one itself. Status is server state behind a guarded `PUT`, while node positions and divider width stay per-browser in `localStorage`. The roadmap gains wrapped variable-height nodes, a status-encoding border, a permanent category column, and wheel zoom; the activity rail is deleted.

**Tech Stack:** Python 3.11+ (`tomllib`), FastAPI, uvicorn, click, dagre, plain ES modules with no build step, pytest, Playwright, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-02-armoire-phase3-design.md`. Read it for intent; this plan is the requirements.

## Global Constraints

- Python 3.11 floor. CI matrix 3.11–3.13 on ubuntu and windows.
- `pathlib` for path handling. One scoped exception to the no-shell-outs rule: `activity.py` invokes `git` via `subprocess.run` with a list argument and `shell=False`, always with a timeout, never interpolating input into a shell string.
- The server binds `127.0.0.1` only. No `--host` option may exist.
- **`serve` never writes to the served folder.** Every write goes to the store and only to the store.
- When the store path is inside the served root, armoire refuses to create or update anything, serves read-only, and says why.
- No CDN at runtime. Every frontend library is a local file under `src/armoire/static/vendor/`, committed so the wheel is self-contained. Never re-run `scripts/vendor.py`.
- No build step; plain ES modules.
- No registry means no roadmap — armoire falls back to the file browser exactly as before.
- `app.py` is routing and error translation only; composition lives in `dashboard.py`.
- Every string in `Registry.issues` leads with a project name followed by `:`; consumers match with `startsWith(name + ':')` and never split on `:`.
- Structural registry problems raise `RegistryError` and nothing else. `app.py` translates only that type; anything else becomes a 500 with a `text/plain` body the client cannot parse as JSON.
- Roadmap visibility is the `hidden` attribute alone. `data-active` must never reappear.
- No `innerHTML`, `outerHTML` or `insertAdjacentHTML` in non-vendor frontend code. Project names, notes and commit subjects are untrusted input and reach the DOM through `textContent` or `setAttribute`.
- Frontend behaviour is verified by Playwright against a live server, never by asserting on JavaScript source text.
- Status values are exactly `not-started`, `active`, `paused`, `done`. Default `active`.
- The divider is clamped to 180–600px.
- Zoom is clamped to 0.35–2.5.
- The suite must report 0 warnings and 0 xfailed.

## Test discipline

This codebase has a documented history of tests that pass while asserting nothing about the code they name. Where a step says **prove it fails**, you must break the code, run the test, paste the actual failure output into your report, and revert. Reasoning that a test *would* fail does not count — six mutations suggested during Phase 2 turned out not to discriminate, each caught only because someone ran them.

Run everything in the foreground. Never background a Playwright run or a test suite.

## File Structure

| File | Responsibility |
|---|---|
| `src/armoire/store.py` | **new** — config dir, folder key, registry and state paths, atomic state write |
| `src/armoire/projects.py` | parse and validate `status`; require `blocked_by` or `category`; load from a given path |
| `src/armoire/dashboard.py` | publish `isolated` and effective `status`; drop the commit count |
| `src/armoire/activity.py` | delete what the rail's removal makes unreachable |
| `src/armoire/app.py` | `PUT /api/status`; publish the served root path |
| `src/armoire/cli.py` | create the stub, migrate a Phase 2 registry, print the store path |
| `src/armoire/static/roadmap.js` | wrapping, variable height, wheel zoom, status chip, done collapse |
| `src/armoire/static/categories.js` | **new** — the category column |
| `src/armoire/static/status.js` | **new** — cycle order, the `PUT` call, optimistic update and rollback |
| `src/armoire/static/divider.js` | **new** — drag, clamp, persist |
| `src/armoire/static/tree.js` | truncation, no horizontal scroll |
| `src/armoire/static/app.js` | root crumb, double-click to roadmap, wire the divider |
| `src/armoire/static/rail.js` | **deleted** |

---

## Task 1: The store

**Files:**
- Create: `src/armoire/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `config_root() -> Path` — the platform config directory for armoire
  - `folder_key(folder: Path) -> str` — stable directory name for a served folder
  - `folder_dir(folder: Path) -> Path` — `config_root() / "folders" / folder_key(folder)`
  - `registry_path(folder: Path) -> Path` — `folder_dir(folder) / "registry.toml"`
  - `state_path(folder: Path) -> Path` — `folder_dir(folder) / "state.json"`
  - `read_state(folder: Path) -> dict` — `{}` when absent or corrupt
  - `write_state(folder: Path, state: dict) -> None` — atomic
  - `store_is_inside(folder: Path) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
import json
import sys

import pytest

from armoire import store


def test_windows_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert store.config_root() == tmp_path / "Roaming" / "armoire"


def test_macos_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / "Library" / "Application Support" / "armoire"


def test_linux_prefers_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert store.config_root() == tmp_path / "cfg" / "armoire"


def test_linux_falls_back_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / ".config" / "armoire"


def test_windows_falls_back_when_appdata_is_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / "AppData" / "Roaming" / "armoire"


def test_the_key_carries_the_folder_name(tmp_path):
    folder = tmp_path / "summer-26"
    folder.mkdir()
    assert store.folder_key(folder).startswith("summer-26-")


def test_the_key_is_stable_across_calls(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    assert store.folder_key(folder) == store.folder_key(folder)


def test_same_basename_in_different_places_gets_different_keys(tmp_path):
    a = tmp_path / "one" / "docs"
    b = tmp_path / "two" / "docs"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert store.folder_key(a) != store.folder_key(b)


def test_the_key_is_filesystem_safe(tmp_path):
    folder = tmp_path / "a b:c*d"
    folder.mkdir()
    key = store.folder_key(folder)
    assert all(c.isalnum() or c in "-_" for c in key), key


def test_a_folder_with_no_usable_name_still_gets_a_key(tmp_path):
    folder = tmp_path / "???"
    folder.mkdir()
    key = store.folder_key(folder)
    # The sanitised tail is empty, so the key is the hash alone -- never "".
    assert len(key) >= 8


def test_reading_state_that_does_not_exist_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    assert store.read_state(tmp_path) == {}


def test_state_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    assert store.read_state(tmp_path) == {"status": {"A": "done"}}


def test_corrupt_state_reads_as_empty_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {}})
    store.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert store.read_state(tmp_path) == {}


def test_state_json_that_is_not_an_object_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {})
    store.state_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    # json.loads succeeds and yields a list, which every caller would then
    # .get() against and crash on.
    assert store.read_state(tmp_path) == {}


def test_writing_state_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    names = sorted(p.name for p in store.folder_dir(tmp_path).iterdir())
    assert names == ["state.json"]


def test_a_second_write_replaces_rather_than_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    store.write_state(tmp_path, {"status": {"B": "paused"}})
    assert json.loads(store.state_path(tmp_path).read_text(encoding="utf-8")) == {
        "status": {"B": "paused"}
    }


def test_the_store_is_detected_inside_a_served_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    assert store.store_is_inside(tmp_path) is True


def test_the_store_is_not_inside_an_unrelated_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    served = tmp_path / "served"
    served.mkdir()
    assert store.store_is_inside(served) is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'armoire.store'`

- [ ] **Step 3: Implement `store.py`**

```python
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
        return Path(os.path.realpath(config_root())).is_relative_to(
            Path(os.path.realpath(folder))
        )
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_store.py -q`
Expected: PASS, 17 tests.

- [ ] **Step 5: Prove two of them discriminate**

Change `folder_key` to return `tail` without the digest. Run
`uv run pytest tests/test_store.py -q`. Paste the failure. Revert.

Change `write_state` to `target.write_text(...)` with no temporary file. Run
`test_writing_state_leaves_no_temporary_file_behind`. It still passes — that
test alone does not prove atomicity, only cleanliness. Say so in your report
rather than claiming coverage the test does not give.

- [ ] **Step 6: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 249 passed, 2 skipped, 0 warnings — plus your 17.

- [ ] **Step 7: Commit**

```bash
git add src/armoire/store.py tests/test_store.py
git commit -m "feat: a per-user store for everything armoire writes"
```

---

## Task 2: Status and the placement rule in the registry

**Files:**
- Modify: `src/armoire/projects.py`
- Test: `tests/test_projects.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `Project.status: str` — one of the four values, defaulting to `"active"`
  - `STATUSES: tuple[str, ...] = ("not-started", "active", "paused", "done")`
  - `load_registry(root: Path, registry_file: Path | None = None) -> Registry | None`

`load_registry` keeps its current behaviour when `registry_file` is None so
nothing breaks before Task 3 rewires it. `root` remains what `paths` resolve
against; `registry_file` is only where the TOML is read from.

**Before you write anything, read this — it is the trap in this task.**

The new placement rule fires on existing fixtures. Every one of these declares
a project with neither `blocked_by` nor `category`, and each will start
producing an issue the moment you implement the rule:

- `tests/test_projects.py`'s `VALID` — `FINM 320`
- `tests/test_app.py`'s `REGISTRY` — `Upstream`
- `tests/test_app.py::test_serving_never_writes_to_disk`'s inline registry — `Docs`
- `tests/conftest.py`'s `sample_root` — none; both its projects have a category

Any existing assertion of the form `registry.issues == []` or a count of issues
will break. **Add `category` to those three fixture projects** rather than
loosening the new rule or the old assertions — a fixture that violates the rule
under test is a fixture that has drifted from what the product now requires.
Report which fixtures you changed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projects.py`. The helper in that file is `write(root, text)`
— not `write_registry` — and it also creates `research/0dte` and
`learning/finm32000` under the root. Use it as the other tests do.

```python
def test_status_defaults_to_active(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n')
    registry = load_registry(tmp_path)
    assert registry.projects[0].status == "active"


def test_each_declared_status_survives_parsing(tmp_path):
    body = ""
    for i, status in enumerate(STATUSES):
        body += f'[[project]]\nname = "P{i}"\npaths = ["."]\ncategory = "x"\nstatus = "{status}"\n'
    write(tmp_path, body)
    registry = load_registry(tmp_path)
    assert [p.status for p in registry.projects] == list(STATUSES)


def test_an_unknown_status_is_an_issue_and_falls_back_to_active(tmp_path):
    write(
        tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\nstatus = "finished"\n'
    )
    registry = load_registry(tmp_path)
    # Falls back rather than raising: a typo must not remove the project.
    assert registry.projects[0].status == "active"
    assert any(i.startswith("A:") and "finished" in i for i in registry.issues)


def test_a_non_string_status_is_an_issue_not_a_crash(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\nstatus = 3\n')
    registry = load_registry(tmp_path)
    assert registry.projects[0].status == "active"
    assert any(i.startswith("A:") for i in registry.issues)


def test_a_project_with_neither_blocked_by_nor_category_is_an_issue(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\n')
    registry = load_registry(tmp_path)
    assert any(i.startswith("A:") and "category" in i for i in registry.issues)


def test_blocked_by_alone_satisfies_the_placement_rule(tmp_path):
    write(
        tmp_path,
        '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n'
        '[[project]]\nname = "B"\npaths = ["."]\nblocked_by = ["A"]\n',
    )
    registry = load_registry(tmp_path)
    assert not any(i.startswith("B:") for i in registry.issues)


def test_category_alone_satisfies_the_placement_rule(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n')
    registry = load_registry(tmp_path)
    assert not any(i.startswith("A:") for i in registry.issues)


def test_the_registry_can_be_read_from_a_file_outside_the_root(tmp_path):
    root = tmp_path / "served"
    root.mkdir()
    (root / "docs").mkdir()
    elsewhere = tmp_path / "store" / "registry.toml"
    elsewhere.parent.mkdir()
    elsewhere.write_text(
        '[[project]]\nname = "A"\npaths = ["docs"]\ncategory = "x"\n', encoding="utf-8"
    )
    registry = load_registry(root, elsewhere)
    # paths still resolve against root, not against the registry's own folder.
    assert registry.projects[0].paths == ("docs",)
    assert registry.issues == []


def test_a_missing_registry_file_outside_the_root_is_no_registry(tmp_path):
    assert load_registry(tmp_path, tmp_path / "nope" / "registry.toml") is None
```

Add `STATUSES` to the imports at the top of the file.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_projects.py -q`
Expected: FAIL — `ImportError: cannot import name 'STATUSES'`

- [ ] **Step 3: Implement**

In `src/armoire/projects.py`:

Add the constant beside `REGISTRY_NAME`:

```python
STATUSES = ("not-started", "active", "paused", "done")
DEFAULT_STATUS = "active"
```

Add the field to `Project`, after `category`:

```python
    status: str = DEFAULT_STATUS
```

`_parse_project` cannot report issues — it raises or returns — so status
validation happens where issues are collected. Parse the raw value through and
validate in `load_registry`:

```python
    return Project(
        name=str(name),
        paths=_as_str_tuple(paths, "paths", str(name)),
        blocked_by=_as_str_tuple(entry.get("blocked_by", ()), "blocked_by", str(name)),
        category=entry.get("category"),
        due=due,
        note=entry.get("note"),
        status=entry.get("status", DEFAULT_STATUS),
    )
```

In `load_registry`, after the duplicate-name check builds `projects`, replace
any project whose status is invalid and record the issue. Do this in the same
loop that already produces referential issues:

```python
    issues: list[str] = []
    known = {p.name for p in projects}
    for position, project in enumerate(projects):
        if project.status not in STATUSES:
            # An issue, not a raise: a typo in one optional field must not
            # remove the project from the graph.
            issues.append(
                f"{project.name}: unknown status {project.status!r}, "
                f"using {DEFAULT_STATUS!r}"
            )
            projects[position] = replace(project, status=DEFAULT_STATUS)
        if not project.blocked_by and not project.category:
            # With neither, the project is in no graph and in no container:
            # there is nowhere on screen for it to be.
            issues.append(
                f"{project.name}: declares neither blocked_by nor category, "
                f"so it cannot be placed"
            )
        for blocker in project.blocked_by:
            ...
```

Import `replace` from `dataclasses`. Note `project.status!r` is formatted
before the replacement, so a non-string value like `3` renders as `3` and the
message stays truthful.

Change the signature and the file lookup:

```python
def load_registry(root: Path, registry_file: Path | None = None) -> Registry | None:
    path = registry_file if registry_file is not None else root / REGISTRY_NAME
    if not path.is_file():
        return None
```

Update the docstring's first line to say the registry is read from
`registry_file` when given, and that `root` is what `paths` resolve against
either way.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_projects.py -q`
Expected: PASS.

- [ ] **Step 5: Prove the placement rule discriminates**

Delete the `if not project.blocked_by and not project.category:` branch. Run
`uv run pytest tests/test_projects.py -q`. Paste the failure. Revert.

- [ ] **Step 6: Full suite and lint, then commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add src/armoire/projects.py tests/test_projects.py
git commit -m "feat: project status and the blocked_by-or-category rule"
```

---

## Task 3: Serve from the store

**Files:**
- Modify: `src/armoire/cli.py`, `src/armoire/app.py`
- Test: `tests/test_cli.py` (create), `tests/test_app.py`

**Interfaces:**
- Consumes: `store.registry_path`, `store.folder_dir`, `store.store_is_inside`, `load_registry(root, registry_file)`.
- Produces:
  - `cli.prepare_store(folder: Path) -> list[str]` — ensures the store exists, migrates a Phase 2 registry, returns the lines to print
  - `create_app(root)` reads the registry from `store.registry_path(root)`

`prepare_store` is a module-level function, not inline in the command, so it is
testable without invoking click.

**Interfaces note for later tasks:** `/api/projects` continues to return
`{"root", "projects", "issues"}` plus `registry: False` or `error`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import pytest

from armoire import cli, store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    return tmp_path / "cfg" / "armoire"


def test_first_serve_creates_a_registry_stub(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    assert store.registry_path(served).is_file()


def test_the_stub_parses_as_toml_and_declares_no_projects(tmp_path, isolated_store):
    from armoire.projects import load_registry

    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    registry = load_registry(served, store.registry_path(served))
    assert registry is not None
    assert registry.projects == []


def test_creating_the_stub_writes_nothing_into_the_served_folder(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    assert list(served.iterdir()) == []


def test_a_second_serve_does_not_overwrite_the_registry(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    store.registry_path(served).write_text(
        '[[project]]\nname = "Mine"\npaths = ["."]\ncategory = "x"\n', encoding="utf-8"
    )
    cli.prepare_store(served)
    assert "Mine" in store.registry_path(served).read_text(encoding="utf-8")


def test_a_phase_two_registry_is_copied_into_the_store(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    (served / "armoire.toml").write_text(
        '[[project]]\nname = "Legacy"\npaths = ["."]\ncategory = "x"\n', encoding="utf-8"
    )
    cli.prepare_store(served)
    assert "Legacy" in store.registry_path(served).read_text(encoding="utf-8")


def test_migration_does_not_delete_the_original(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    legacy = served / "armoire.toml"
    legacy.write_text('[[project]]\nname = "Legacy"\npaths = ["."]\ncategory = "x"\n', "utf-8")
    cli.prepare_store(served)
    # Deleting it would itself be a write to the served folder.
    assert legacy.is_file()


def test_migration_reports_which_file_is_now_authoritative(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    (served / "armoire.toml").write_text('[[project]]\nname = "L"\npaths = ["."]\ncategory = "x"\n', "utf-8")
    lines = cli.prepare_store(served)
    joined = "\n".join(lines)
    assert str(store.registry_path(served)) in joined


def test_a_store_inside_the_served_folder_refuses_to_write(tmp_path, monkeypatch):
    served = tmp_path / "home"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: served / "cfg" / "armoire")
    lines = cli.prepare_store(served)
    assert not store.registry_path(served).exists()
    assert any("inside" in line for line in lines)


def test_the_refusal_leaves_the_served_folder_untouched(tmp_path, monkeypatch):
    served = tmp_path / "home"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: served / "cfg" / "armoire")
    cli.prepare_store(served)
    assert list(served.iterdir()) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — `AttributeError: module 'armoire.cli' has no attribute 'prepare_store'`

- [ ] **Step 3: Implement `prepare_store`**

In `src/armoire/cli.py`:

```python
from armoire import store
from armoire.projects import REGISTRY_NAME

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
# status = "active"                # not-started | active | paused | done
# note = "One line about it."
"""


def prepare_store(folder: Path) -> list[str]:
    """Ensure the store exists for this folder. Returns lines to print.

    Writing anything here would land inside the served tree when the store is
    a descendant of it -- a home directory, or %APPDATA% itself. In that case
    armoire serves read-only and says so, rather than quietly breaking the one
    guarantee it makes.
    """
    if store.store_is_inside(folder):
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
        # Copied, not moved: deleting it would be a write to the served folder.
        target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        return [
            f"  migrated {legacy} into the store",
            f"  {target} is now authoritative; the copy in the folder is ignored",
        ]

    target.write_text(STUB, encoding="utf-8")
    return [f"  no registry yet - created {target}", "  edit it and reload to see the roadmap"]
```

Call it from `serve`, between the two existing `click.echo` calls and the
`uvicorn.run`:

```python
    click.echo(f"armoire serving {root}")
    click.echo(f"  http://127.0.0.1:{port}")
    for line in prepare_store(root):
        click.echo(line)
```

- [ ] **Step 4: Point `app.py` at the store**

Both `load_registry(root)` call sites in `app.py` become
`load_registry(root, store.registry_path(root))`. Import `store`.

- [ ] **Step 5: Update the existing app tests**

`tests/test_app.py` and `tests/conftest.py` write `armoire.toml` into the
served root. Every such fixture must now write to `store.registry_path(root)`
instead, with `store.config_root` monkeypatched to a tmp directory so no test
touches the real user config.

Add to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _isolated_store(tmp_path_factory, monkeypatch):
    """No test may read or write the developer's real armoire store."""
    base = tmp_path_factory.mktemp("armoire-store")
    monkeypatch.setattr(store, "config_root", lambda: base)
    return base
```

Session-scoped server fixtures cannot use a function-scoped monkeypatch. For
those, set the environment before the app is created — `APPDATA` on Windows
and `XDG_CONFIG_HOME` elsewhere both feed `config_root` — or write the registry
through `store.registry_path` after pointing `config_root` with
`monkeypatch.setenv` at session scope via `pytest.MonkeyPatch.context()`. Pick
one approach and use it consistently; say which in your report.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. Every previously passing test still passes.

- [ ] **Step 7: Prove the refusal discriminates**

Delete the `store_is_inside` branch from `prepare_store`. Run
`uv run pytest tests/test_cli.py -q`. Paste the failure. Revert.

- [ ] **Step 8: Commit**

```bash
git add src/armoire/cli.py src/armoire/app.py tests/test_cli.py tests/test_app.py tests/conftest.py
git commit -m "feat: read the registry from the store, migrate a Phase 2 one"
```

---

## Task 4: Isolation, effective status, and removing the commit count

**Files:**
- Modify: `src/armoire/dashboard.py`, `src/armoire/activity.py`
- Test: `tests/test_dashboard.py`, `tests/test_activity.py`

**Interfaces:**
- Consumes: `store.read_state`, `Project.status`, `STATUSES`.
- Produces: each row from `project_rows` gains `isolated: bool` and an
  effective `status: str`, and loses `commits` and `last`.

Effective status is `state.json`'s value when present and valid, otherwise the
registry's.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dashboard.py — append
def test_a_project_with_no_edges_is_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    assert project_rows(tmp_path, registry)[0]["isolated"] is True


def test_a_project_that_blocks_something_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(tmp_path, registry)}
    assert rows["A"]["isolated"] is False


def test_a_project_that_is_blocked_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(tmp_path, registry)}
    assert rows["B"]["isolated"] is False


def test_an_edge_to_an_unknown_project_does_not_make_it_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), blocked_by=("Ghost",), category="x")])
    # The edge is never drawn -- the blocker does not exist -- so A stands alone
    # on the canvas and belongs in a category container.
    assert project_rows(tmp_path, registry)[0]["isolated"] is True


def test_stored_status_overrides_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="active")])
    assert project_rows(tmp_path, registry)[0]["status"] == "done"


def test_the_registry_status_is_used_when_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(tmp_path, registry)[0]["status"] == "paused"


def test_a_corrupt_stored_status_falls_back_to_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "nonsense"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(tmp_path, registry)[0]["status"] == "paused"


def test_rows_no_longer_carry_a_commit_count(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    row = project_rows(tmp_path, registry)[0]
    assert "commits" not in row and "last" not in row
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -q`
Expected: FAIL — `KeyError: 'isolated'`

- [ ] **Step 3: Implement**

Rewrite `project_rows`:

```python
def project_rows(root: Path, registry: Registry) -> list[dict]:
    known = {p.name for p in registry.projects}
    # Only edges that will actually be drawn count. An edge naming a project
    # that does not exist is reported as an issue and never rendered, so the
    # node still stands alone and belongs in a category container.
    blocks = {b for p in registry.projects for b in p.blocked_by if b in known}
    stored = store.read_state(root).get("status", {})
    if not isinstance(stored, dict):
        stored = {}

    listed = []
    for project in registry.projects:
        connected = project.name in blocks or any(b in known for b in project.blocked_by)
        override = stored.get(project.name)
        listed.append(
            asdict(project)
            | {"paths": list(project.paths), "blocked_by": list(project.blocked_by)}
            | {
                "isolated": not connected,
                "status": override if override in STATUSES else project.status,
            }
        )
    return listed
```

Import `store` and `STATUSES`; drop the `activity_for` import.

- [ ] **Step 4: Delete what the rail's removal orphans**

`activity_for` and anything only it uses — including `_newest_mtime` and the
`Activity` dataclass if nothing else references them — come out of
`activity.py`. `recent_commits` and the shared `_resolve` jail stay. Delete the
now-dead tests in `tests/test_activity.py`; keep every test that covers
`recent_commits` and `_resolve`, including the path-jail ones.

Verify nothing else imports what you removed:

```bash
grep -rn "activity_for\|_newest_mtime" src tests
```

Expected: no matches.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Prove the unknown-blocker case discriminates**

Change `connected` to `project.name in blocks or bool(project.blocked_by)`. Run
`test_an_edge_to_an_unknown_project_does_not_make_it_connected`. Paste the
failure. Revert.

- [ ] **Step 7: Commit**

```bash
git add src/armoire/dashboard.py src/armoire/activity.py tests/
git commit -m "feat: isolation and effective status; drop the commit count"
```

---

## Task 5: The status write endpoint

**Files:**
- Modify: `src/armoire/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `store.read_state`, `store.write_state`, `store.store_is_inside`, `STATUSES`.
- Produces: `PUT /api/status` accepting `{"name": str, "status": str}`.

Responses: 200 `{"name", "status"}` on success; 400 unknown status; 403 missing
`X-Armoire` or foreign `Origin`, and also when the store is inside the served
root; 404 unknown project.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app.py — append. REGISTRY is the existing module-level string.
HEADERS = {"X-Armoire": "1"}


def _client_with_registry(tmp_path):
    (tmp_path / "docs").mkdir(exist_ok=True)
    store.registry_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    store.registry_path(tmp_path).write_text(REGISTRY, encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_a_status_edit_is_stored(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put("/api/status", json={"name": "Downstream", "status": "done"}, headers=HEADERS)
    assert response.status_code == 200
    assert store.read_state(tmp_path)["status"]["Downstream"] == "done"


def test_the_stored_status_comes_back_from_the_projects_endpoint(tmp_path):
    client = _client_with_registry(tmp_path)
    client.put("/api/status", json={"name": "Downstream", "status": "paused"}, headers=HEADERS)
    rows = {r["name"]: r for r in client.get("/api/projects").json()["projects"]}
    assert rows["Downstream"]["status"] == "paused"


def test_an_unknown_status_is_rejected(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put("/api/status", json={"name": "Downstream", "status": "finished"}, headers=HEADERS)
    assert response.status_code == 400
    assert store.read_state(tmp_path) == {}


def test_an_unknown_project_is_rejected(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put("/api/status", json={"name": "Ghost", "status": "done"}, headers=HEADERS)
    assert response.status_code == 404
    assert store.read_state(tmp_path) == {}


def test_a_request_without_the_header_is_refused(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put("/api/status", json={"name": "Downstream", "status": "done"})
    # 127.0.0.1 keeps other machines out; it does not keep other tabs out.
    assert response.status_code == 403
    assert store.read_state(tmp_path) == {}


def test_a_request_from_a_foreign_origin_is_refused(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put(
        "/api/status",
        json={"name": "Downstream", "status": "done"},
        headers=HEADERS | {"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert store.read_state(tmp_path) == {}


def test_a_request_from_our_own_origin_is_allowed(tmp_path):
    client = _client_with_registry(tmp_path)
    response = client.put(
        "/api/status",
        json={"name": "Downstream", "status": "done"},
        headers=HEADERS | {"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_a_status_edit_does_not_write_to_the_served_folder(tmp_path):
    client = _client_with_registry(tmp_path)
    before = folder_snapshot(tmp_path)
    client.put("/api/status", json={"name": "Downstream", "status": "done"}, headers=HEADERS)
    assert folder_snapshot(tmp_path) == before
```

**`snapshot` does not exist as a shared helper yet.** There are two nested
copies — one inside `test_serving_never_writes_to_disk` in `tests/test_app.py`,
one inside `test_dragging_does_not_write_to_the_served_folder` in
`tests/test_roadmap.py` — and this task needs a third caller, with a fourth
coming in Task 11.

Extract it to `tests/conftest.py` as a module-level function first, then use it
from all callers:

```python
def folder_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Every file under root, keyed by relative path, with mtime and content.

    mtime as well as sha256: a pure-metadata touch -- an ill-judged os.utime,
    or a git operation that rewrites an index -- is invisible to a content hash
    alone, and the read-only guarantee has to catch both.

    Keyed by relative path, not by name: two files called README.md in
    different directories collapsed to one entry under the old keying and one
    of them went unchecked.
    """
    return {
        p.relative_to(root).as_posix(): (
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
```

Replace both nested copies with calls to it. The two existing tests must still
pass unchanged in behaviour — if either starts failing after the extraction,
the copies differed and you have found a real bug; report it rather than
papering over it.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_app.py -q -k status`
Expected: FAIL — 405, the route does not exist.

- [ ] **Step 3: Implement**

In `create_app`, after the `/api/project/{name}` route:

```python
    @app.put("/api/status")
    def set_status(payload: dict, request: Request) -> dict:
        # The bind address stops other machines, not other tabs: any page in
        # any browser on this machine can reach 127.0.0.1. A custom header
        # cannot be set cross-origin without a CORS preflight, and armoire
        # answers none and installs no CORS middleware, so the browser refuses
        # the request before it is sent. HTML form posts cannot set headers at
        # all, which closes the other route in.
        if request.headers.get("X-Armoire") != "1":
            raise HTTPException(status_code=403, detail="missing X-Armoire header")
        origin = request.headers.get("Origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="foreign origin")
        if store.store_is_inside(root):
            raise HTTPException(
                status_code=403, detail="the armoire store is inside the served folder"
            )

        status = payload.get("status")
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"unknown status {status!r}")
        name = payload.get("name")

        try:
            registry = load_registry(root, store.registry_path(root))
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if registry is None or not any(p.name == name for p in registry.projects):
            raise HTTPException(status_code=404, detail="no such project")

        state = store.read_state(root)
        # An entry naming a project the registry no longer has is kept, not
        # pruned: renaming a project and renaming it back should not lose its
        # status.
        statuses = state.get("status")
        state["status"] = (statuses if isinstance(statuses, dict) else {}) | {name: status}
        store.write_state(root, state)
        return {"name": name, "status": status}
```

Import `Request` from `fastapi` and `STATUSES` from `armoire.projects`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Prove the guard discriminates**

Delete the `X-Armoire` check. Run `test_a_request_without_the_header_is_refused`.
Paste the failure. Revert. Do the same for the `Origin` check.

- [ ] **Step 6: Extend the read-only guarantee test**

`test_serving_never_writes_to_disk` must exercise the status write inside its
checksum window. Add a `PUT` between `before = folder_snapshot(root)` and the
final assertion, using the registry the test already writes to the store.

That test's inline registry declares `Docs` with no category, so Task 2's
placement rule now flags it — give it one while you are here, and use `Docs` as
the name in the `PUT`.

Prove it: make `set_status` also `(root / "touched").write_text("x")`. Run the
test. Paste the failure. Revert.

- [ ] **Step 7: Commit**

```bash
git add src/armoire/app.py tests/test_app.py
git commit -m "feat: a guarded status write endpoint"
```

---

## Task 6: Wrapped, variable-height nodes

**Files:**
- Modify: `src/armoire/static/roadmap.js`, `src/armoire/static/app.css`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Produces: `layout(projects, heights)` takes a `Map<string, number>`; nodes carry `data-name` as before.

The commit badge is removed in this task.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roadmap.py — append
def test_a_long_note_stays_inside_its_node(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    for name in page.locator(".node").evaluate_all(
        "nodes => nodes.map(n => n.dataset.name)"
    ):
        node = page.locator(f'.node[data-name="{name}"]')
        rect = node.locator("rect").bounding_box()
        for i in range(node.locator("text").count()):
            text = node.locator("text").nth(i).bounding_box()
            if text is None:
                continue
            assert text["x"] >= rect["x"] - 1, name
            assert text["x"] + text["width"] <= rect["x"] + rect["width"] + 1, name
            assert text["y"] + text["height"] <= rect["y"] + rect["height"] + 1, name


def test_a_long_note_wraps_onto_several_lines(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    counts = page.locator(".node .node-sub tspan").count()
    assert counts >= 2


def test_nodes_no_longer_show_a_commit_count(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator(".node .node-badge").count() == 0
```

The `sample_root` fixture's registry must contain a project whose `note` is
long enough to wrap — at least 120 characters. Extend the existing fixture
rather than adding a new one, and check no existing assertion depends on the
old note text.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -q -k "long_note or commit_count"`
Expected: FAIL — text extends past the rect; `.node-badge` count is not 0.

- [ ] **Step 3: Implement wrapping**

Replace the fixed `NODE_H` with a computed height. Add above `layout`:

```javascript
const NODE_PAD_X = 12;
const TITLE_Y = 24;
const LINE_H = 15;
const NODE_MIN_H = 40;

// SVG <text> does not wrap. Measure in the live SVG rather than guessing from
// character counts: font metrics are not knowable ahead of time, and the
// previous fixed-height node let every long note render outside its own box.
function wrapLines(canvas, text, maxWidth) {
  const probe = svgEl('text', { class: 'node-sub', visibility: 'hidden' });
  canvas.append(probe);
  const lines = [];
  let current = '';
  const push = () => { if (current) lines.push(current); current = ''; };
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const candidate = current ? `${current} ${word}` : word;
    probe.textContent = candidate;
    if (probe.getComputedTextLength() <= maxWidth) { current = candidate; continue; }
    push();
    probe.textContent = word;
    if (probe.getComputedTextLength() <= maxWidth) { current = word; continue; }
    // A single word wider than the box -- a long path or an unbroken token.
    // Break it rather than let it escape the rect.
    let chunk = '';
    for (const ch of word) {
      probe.textContent = chunk + ch;
      if (probe.getComputedTextLength() > maxWidth && chunk) { lines.push(chunk); chunk = ch; }
      else chunk += ch;
    }
    current = chunk;
  }
  push();
  probe.remove();
  return lines;
}

function nodeHeight(lineCount) {
  return Math.max(NODE_MIN_H, TITLE_Y + 6 + lineCount * LINE_H + 8);
}
```

`layout` takes the heights:

```javascript
function layout(projects, heights) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', align: 'UL', nodesep: 28, ranksep: 72, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  const known = new Set(projects.map((p) => p.name));
  for (const project of projects) {
    g.setNode(project.name, { width: NODE_W, height: heights.get(project.name) });
  }
  ...
}
```

In `renderRoadmap`, compute lines and heights before laying out. The probe
needs the canvas in the document, so this runs after `canvas.replaceChildren()`
and before `layout`:

```javascript
  canvas.replaceChildren();
  const wrapped = new Map();
  const heights = new Map();
  for (const project of projects) {
    const lines = wrapLines(canvas, project.due || project.note || '', NODE_W - NODE_PAD_X * 2);
    wrapped.set(project.name, lines);
    heights.set(project.name, nodeHeight(lines.length));
  }
  const g = layout(projects, heights);
```

Every `NODE_H` in positioning and edge geometry becomes the node's own height.
`edgePath` uses only `x`, so it is unaffected; the `translate` in the node loop
and in `place()` becomes:

```javascript
      transform: `translate(${pos.x - NODE_W / 2},${pos.y - heights.get(project.name) / 2})`,
```

`place(name)` must read the same map — hoist `heights` so it is in scope.

The subtitle becomes one `<tspan>` per line, and the badge is deleted:

```javascript
    const lines = wrapped.get(project.name);
    if (lines.length) {
      const sub = svgEl('text', { x: NODE_PAD_X, y: TITLE_Y + 18, class: 'node-sub' });
      for (const [i, line] of lines.entries()) {
        const span = svgEl('tspan', { x: NODE_PAD_X, dy: i === 0 ? 0 : LINE_H });
        span.textContent = line;
        sub.append(span);
      }
      group.append(sub);
    }
```

The warn marker's `y` becomes `heights.get(project.name) - 10`, and the rect's
`height` becomes the node's height.

Remove `.node .node-badge` from `app.css`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_roadmap.py -q`
Expected: PASS.

- [ ] **Step 5: Prove the containment test discriminates**

Set `nodeHeight` to `return NODE_MIN_H;`. Run
`test_a_long_note_stays_inside_its_node`. Paste the failure. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/armoire/static/roadmap.js src/armoire/static/app.css tests/
git commit -m "feat: wrap node notes and size nodes to fit"
```

---

## Task 7: Status on the canvas

**Files:**
- Create: `src/armoire/static/status.js`
- Modify: `src/armoire/static/roadmap.js`, `src/armoire/static/app.css`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `PUT /api/status` from Task 5; `status` on each row from Task 4.
- Produces:
  - `STATUS_ORDER = ['not-started', 'active', 'paused', 'done']`
  - `nextStatus(current: string): string`
  - `setStatus(name: string, status: string): Promise<void>` — throws on non-2xx

Class names: the node group carries `status-not-started`, `status-active`,
`status-paused` or `status-done`. `blocked` stays on the group but now means
"at least one blocker is not done".

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roadmap.py — append
def test_the_four_statuses_render_four_distinct_borders(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    seen = set()
    for status in ["not-started", "active", "paused", "done"]:
        page.evaluate(
            "s => document.querySelector('.node').setAttribute('class', 'node cat-0 status-' + s)",
            status,
        )
        seen.add(
            page.locator(".node rect").first.evaluate(
                "r => getComputedStyle(r).strokeWidth + '|' + getComputedStyle(r).strokeDasharray"
            )
        )
    assert len(seen) == 4, seen


def test_clicking_the_chip_cycles_the_status(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Upstream"]')
    before = node.get_attribute("class")
    node.locator(".status-chip").click()
    page.wait_for_function(
        "cls => document.querySelector('.node[data-name=\\"Docs\\"]').className.baseVal !== cls",
        arg=before,
    )
    assert node.get_attribute("class") != before


def test_clicking_the_chip_does_not_open_the_detail_view(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.locator('.node[data-name="Upstream"] .status-chip').click()
    page.wait_for_timeout(300)
    assert "#/project/" not in page.url


def test_a_status_edit_survives_a_fresh_browser_context(live_server, page, browser):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    chip = page.locator('.node[data-name="Upstream"] .status-chip')
    for _ in range(3):
        chip.click()
        page.wait_for_timeout(150)
    after = page.locator('.node[data-name="Upstream"]').get_attribute("class")

    # A fresh context shares no localStorage. If status survives this, it is
    # server state -- which is the whole point of moving it out of the browser.
    context = browser.new_context()
    try:
        fresh = context.new_page()
        fresh.goto(f"{live_server}/#/")
        fresh.wait_for_selector(".node")
        assert fresh.locator('.node[data-name="Upstream"]').get_attribute("class") == after
    finally:
        context.close()


def test_marking_the_last_blocker_done_unblocks_its_dependent(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    dependent = page.locator('.node[data-name="Downstream"]')
    assert "blocked" in dependent.get_attribute("class")
    blocker = page.locator('.node[data-name="Upstream"] .status-chip')
    while "status-done" not in page.locator('.node[data-name="Upstream"]').get_attribute("class"):
        blocker.click()
        page.wait_for_timeout(150)
    page.wait_for_function(
        "() => !document.querySelector('.node[data-name=\\"Downstream\\"]')"
        ".className.baseVal.includes('blocked')"
    )
```

`Upstream` and `Downstream` are `sample_root`'s two projects: `Downstream` is
blocked by `Upstream`. These are the real names — verified against
`tests/conftest.py` — so use them exactly.

**These tests mutate server state.** `sample_root` is session-scoped, so a
status edit in one test is visible to every later test in the file. Either give
these tests their own function-scoped server fixture, or have each reset the
status it changed in a `finally`. Choose one, and say which in your report —
a test that passes only when run in file order is worse than no test.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -q -k "status or chip or unblock"`
Expected: FAIL — no `.status-chip` element.

- [ ] **Step 3: Implement `status.js`**

```javascript
// Status is server state, not browser state: it is a claim about the work and
// must be the same in every browser. Positions are the opposite and stay in
// localStorage.

export const STATUS_ORDER = ['not-started', 'active', 'paused', 'done'];

const GLYPH = {
  'not-started': '○',
  active: '●',
  paused: '◐',
  done: '✓',
};

export function nextStatus(current) {
  const at = STATUS_ORDER.indexOf(current);
  return STATUS_ORDER[(at + 1) % STATUS_ORDER.length];
}

export function glyphFor(status) {
  return GLYPH[status] || GLYPH.active;
}

export async function setStatus(name, status) {
  const response = await fetch('/api/status', {
    method: 'PUT',
    // The server requires this header. A cross-origin page cannot set it
    // without a preflight armoire never answers, which is what stops any
    // other tab writing here.
    headers: { 'Content-Type': 'application/json', 'X-Armoire': '1' },
    body: JSON.stringify({ name, status }),
  });
  if (!response.ok) throw new Error(`status ${response.status}`);
}
```

- [ ] **Step 4: Wire it into `roadmap.js`**

Track statuses in a `Map`, seeded from the payload. Recompute blocked-ness
from it rather than from `blocked_by` alone:

```javascript
  const statuses = new Map(projects.map((p) => [p.name, p.status]));

  function isBlocked(project) {
    // Blocked means "waiting on something unfinished", not "has a blocker".
    // A done project is waiting on nothing by definition.
    if (statuses.get(project.name) === 'done') return false;
    return project.blocked_by.some((b) => known.has(b) && statuses.get(b) !== 'done');
  }
```

`known` must be in scope in `renderRoadmap` — build it there rather than only
inside `layout`.

The group's class becomes:

```javascript
      class: `node ${categoryClass(project.category, order)} status-${statuses.get(project.name)}${
        isBlocked(project) ? ' blocked' : ''
      }`,
```

Append the chip after the title:

```javascript
    const chip = svgEl('text', {
      x: NODE_W - NODE_PAD_X, y: TITLE_Y, class: 'status-chip',
      'text-anchor': 'end', tabindex: '0', role: 'button',
    });
    chip.textContent = glyphFor(statuses.get(project.name));
    chip.setAttribute('aria-label', `Status: ${statuses.get(project.name)}. Click to change.`);
    const cycle = async (event) => {
      // The chip lives inside the node group, whose own click handler opens
      // the detail view. Without stopPropagation every status change would
      // also navigate away from the screen showing it.
      event.stopPropagation();
      event.preventDefault();
      const previous = statuses.get(project.name);
      const wanted = nextStatus(previous);
      statuses.set(project.name, wanted);
      applyStatus(project.name);
      try {
        await setStatus(project.name, wanted);
      } catch {
        // The write failed; the screen must not keep claiming it succeeded.
        statuses.set(project.name, previous);
        applyStatus(project.name);
      }
    };
    chip.addEventListener('click', cycle);
    chip.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') cycle(event);
    });
    group.append(chip);
```

`applyStatus(name)` rewrites the class, glyph and `aria-label` for that node
and every node whose blocked-ness depends on it, and re-styles the outgoing
edges. Because unblocking is transitive through one hop only — a dependent's
class depends on its blockers' statuses — recompute all nodes' `blocked` class
after any change. Seventeen nodes is nothing; do the simple thing:

```javascript
  function applyStatus(changed) {
    for (const project of projects) {
      const group = nodeLayer.querySelector(`[data-name="${CSS.escape(project.name)}"]`);
      if (!group) continue;
      const status = statuses.get(project.name);
      group.setAttribute(
        'class',
        `node ${categoryClass(project.category, order)} status-${status}${
          isBlocked(project) ? ' blocked' : ''
        }`,
      );
      const chip = group.querySelector('.status-chip');
      if (chip) {
        chip.textContent = glyphFor(status);
        chip.setAttribute('aria-label', `Status: ${status}. Click to change.`);
      }
    }
    for (const edge of edges) {
      edge.path.classList.toggle('from-done', statuses.get(edge.from) === 'done');
    }
  }
```

Call `applyStatus()` once after the node loop so the initial edge classes are
right.

**Done collapse:** when a project's status is `done`, its height is
`NODE_MIN_H` and its note is not rendered. Compute this in the height pass:

```javascript
    const done = project.status === 'done';
    const lines = done ? [] : wrapLines(canvas, project.due || project.note || '', ...);
```

Collapse follows the payload's status, not a later click: re-laying out the
whole graph mid-gesture would move every node under the pointer. A click
changes colour and weight immediately; the collapse appears on the next load.
Say this in a comment so nobody "fixes" it into a reflow.

- [ ] **Step 5: Style it**

Replace `.node.blocked rect` in `app.css`. Status owns the border; blocked owns
the fill; edge style owns the blocker's state:

```css
/* Three signals, three channels. Phase 2 gave "blocked" a heavy outline and
   Phase 3 gives status the border, so they would have collided: a bold border
   would have meant both "active" and "blocked" at once. Fill and edge style
   carry the other two. */
.node.status-not-started rect { stroke-width: 1; stroke-dasharray: 2 3; }
.node.status-active rect      { stroke-width: 2.5; }
.node.status-paused rect      { stroke-width: 1.5; stroke-dasharray: 6 4; }
.node.status-done rect        { stroke-width: 1; }
.node.status-done             { opacity: 0.55; }
.node.status-done text        { text-decoration: line-through; }
.node.blocked rect            { fill: var(--subtle); }
.status-chip { font-size: 12px; cursor: pointer; }
.edge.from-done { stroke-dasharray: 4 4; opacity: 0.5; }
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_roadmap.py -q`
Expected: PASS.

- [ ] **Step 7: Prove two of them discriminate**

Remove `event.stopPropagation()` from `cycle`. Run
`test_clicking_the_chip_does_not_open_the_detail_view`. Paste the failure.
Revert.

Change `isBlocked` to `return project.blocked_by.length > 0`. Run
`test_marking_the_last_blocker_done_unblocks_its_dependent`. Paste the failure.
Revert.

- [ ] **Step 8: Commit**

```bash
git add src/armoire/static/status.js src/armoire/static/roadmap.js src/armoire/static/app.css tests/
git commit -m "feat: status on the canvas, and done unblocks its dependents"
```

---

## Task 8: Wheel zoom

**Files:**
- Modify: `src/armoire/static/roadmap.js`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: the `scale` and `pan` state already inside `renderRoadmap`.
- Produces: no new exports. `zoomBy(factor)` keeps its signature; a new
  internal `zoomAt(factor, clientX, clientY)` backs both.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roadmap.py — append
def test_the_wheel_zooms_in(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, -240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) > 100


def test_the_wheel_zooms_out(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, 240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) < 100


def test_the_wheel_does_not_scroll_the_page(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, 240)
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.scrollY") == 0


def test_zoom_stays_within_its_limits(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    for _ in range(40):
        page.mouse.wheel(0, -240)
    page.wait_for_timeout(200)
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) <= 250
    for _ in range(80):
        page.mouse.wheel(0, 240)
    page.wait_for_timeout(200)
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) >= 35


def test_the_point_under_the_cursor_stays_put(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    box = page.locator('.node[data-name="Upstream"] rect').bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    after = page.locator('.node[data-name="Upstream"] rect').bounding_box()
    acx, acy = after["x"] + after["width"] / 2, after["y"] + after["height"] / 2
    # Anchored zoom: the point under the pointer does not slide away from it.
    assert abs(acx - cx) < 12 and abs(acy - cy) < 12
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -q -k wheel`
Expected: FAIL — the zoom level stays at `100%`; `wait_for_function` times out.

- [ ] **Step 3: Implement**

Replace the `zoomBy` body with a shared anchored implementation:

```javascript
  function zoomAt(factor, clientX, clientY) {
    const point = canvas.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const local = point.matrixTransform(canvas.getScreenCTM().inverse());
    const next = Math.min(2.5, Math.max(0.35, scale * factor));
    // Keep the graph point under the cursor under the cursor: solve
    // local = graph * next + pan' for pan', where graph is that point in
    // graph coordinates at the current scale.
    const graphX = (local.x - pan.x) / scale;
    const graphY = (local.y - pan.y) / scale;
    pan = { x: local.x - graphX * next, y: local.y - graphY * next };
    scale = next;
    applyViewport();
  }
```

Add the listener beside the other four, inside the `signal` group:

```javascript
  // passive: false, and preventDefault -- a passive listener cannot prevent
  // the default and the browser ignores the call, so the page would scroll
  // behind the canvas on every zoom.
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.1 : 1 / 1.1, event.clientX, event.clientY);
  }, { signal, passive: false });
```

The returned `zoomBy` keeps working for the buttons by anchoring at the
canvas centre:

```javascript
    zoomBy(factor) {
      const box = canvas.getBoundingClientRect();
      zoomAt(factor, box.left + box.width / 2, box.top + box.height / 2);
    },
```

- [ ] **Step 4: Run the tests, then prove one discriminates**

Run: `uv run pytest tests/test_roadmap.py -q`

Remove `event.preventDefault()` and set `passive: true`. Run
`test_the_wheel_does_not_scroll_the_page`. If it still passes because the page
does not overflow, say so — and make the page overflow in the test setup so the
assertion is real, or delete the test rather than keep one that cannot fail.

Change `zoomAt` to ignore `clientX`/`clientY` and keep `pan` unchanged. Run
`test_the_point_under_the_cursor_stays_put`. Paste the failure. Revert.

- [ ] **Step 5: Commit**

```bash
git add src/armoire/static/roadmap.js tests/test_roadmap.py
git commit -m "feat: wheel zoom anchored at the cursor"
```

---

## Task 9: The category column, and deleting the rail

**Files:**
- Create: `src/armoire/static/categories.js`
- Delete: `src/armoire/static/rail.js`
- Modify: `src/armoire/static/app.js`, `src/armoire/static/index.html`, `src/armoire/static/app.css`, `src/armoire/static/roadmap.js`
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `isolated` from Task 4; `glyphFor`, `nextStatus`, `setStatus` from Task 7.
- Produces: `renderCategories(container, data, onOpen) -> void`

`renderRoadmap` must now draw only the non-isolated projects. Filter in
`app.js` before calling it, so `roadmap.js` keeps one job.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roadmap.py — append
def test_isolated_projects_leave_the_graph(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator('.node[data-name="Standalone"]').count() == 0


def test_isolated_projects_appear_in_a_category_container(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    assert page.locator('#categories [data-name="Standalone"]').count() == 1


def test_each_category_gets_its_own_container(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    titles = page.locator("#categories .category h3").all_inner_texts()
    assert len(titles) == len(set(titles))


def test_a_category_entry_opens_the_project(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    page.locator('#categories [data-name="Standalone"] .entry-name').click()
    page.wait_for_url("**/#/project/Standalone")


def test_the_details_toggle_is_gone(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator("#rail-toggle").count() == 0
    assert page.locator("#rail").count() == 0


def test_the_status_strip_reports_registry_issues(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    # sample_root's registry has at least one issue; the rail used to be the
    # only place it was visible.
    assert "issue" in page.locator("#status").inner_text()
```

`Standalone` is a project you must add to `sample_root`'s registry: no
`blocked_by`, a `category`, and a `note`. Add a second isolated project in a
different category so `test_each_category_gets_its_own_container` is not
vacuous with one container.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -q -k "categor or isolated or details"`
Expected: FAIL — no `#categories` element.

- [ ] **Step 3: Implement `categories.js`**

```javascript
// Projects that participate in no dependency have no place in the graph.
// Phase 2 let dagre park them mid-canvas, where they pushed the real roots
// off-centre and read as part of a structure they are not in.

import { glyphFor, nextStatus, setStatus } from './status.js';

export function renderCategories(container, data, onOpen) {
  container.replaceChildren();
  const isolated = (data.projects || []).filter((p) => p.isolated);
  if (!isolated.length) return;

  const groups = new Map();
  for (const project of isolated) {
    const key = project.category || 'Uncategorised';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(project);
  }

  for (const [name, members] of groups) {
    const section = document.createElement('section');
    section.className = 'category';
    const heading = document.createElement('h3');
    heading.textContent = name;
    section.append(heading);

    const list = document.createElement('ul');
    for (const project of members) {
      const item = document.createElement('li');
      item.className = `entry status-${project.status}`;
      item.setAttribute('data-name', project.name);

      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'status-chip';
      chip.textContent = glyphFor(project.status);
      chip.setAttribute('aria-label', `Status: ${project.status}. Click to change.`);
      let status = project.status;
      chip.addEventListener('click', async (event) => {
        event.stopPropagation();
        const previous = status;
        status = nextStatus(status);
        chip.textContent = glyphFor(status);
        item.className = `entry status-${status}`;
        try {
          await setStatus(project.name, status);
        } catch {
          status = previous;
          chip.textContent = glyphFor(status);
          item.className = `entry status-${status}`;
        }
      });

      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'entry-name';
      label.textContent = project.name;
      label.addEventListener('click', () => onOpen(project.name));

      item.append(chip, label);
      if (project.note) {
        const note = document.createElement('p');
        note.className = 'entry-note';
        note.textContent = project.note;
        item.append(note);
      }
      list.append(item);
    }
    section.append(list);
    container.append(section);
  }
}
```

- [ ] **Step 4: Rewire `index.html` and `app.js`**

In `index.html`, replace the `rail-toggle` button and `rail` aside with:

```html
  <aside id="categories" aria-label="Projects outside the roadmap"></aside>
```

In `app.js`: drop the `initRail` import and call; import `renderCategories`;
filter the graph payload; report issues in the status strip.

```javascript
  const connected = { ...data, projects: data.projects.filter((p) => !p.isolated) };
  roadmapView = renderRoadmap(canvas, connected, navigateProject, roadmapListeners.signal);
  renderCategories(document.getElementById('categories'), data, navigateProject);
  ...
  const issues = (data.issues || []).length;
  status.textContent = issues
    ? `${data.projects.length} projects · ${issues} issue${issues === 1 ? '' : 's'}`
    : `${data.projects.length} projects`;
```

Delete `src/armoire/static/rail.js` and its tests in `tests/test_roadmap.py`.

- [ ] **Step 5: Style it**

```css
#categories {
  width: 240px;
  flex: 0 0 240px;
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 12px;
}
.category { margin-bottom: 16px; border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 10px; }
.category h3 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.category ul { list-style: none; margin: 0; padding: 0; }
.entry { padding: 4px 0; }
.entry-name { background: none; border: 0; padding: 0; color: var(--link); cursor: pointer; font: inherit; }
.entry-note { margin: 2px 0 0; font-size: 11px; color: var(--muted); }
.entry.status-done { opacity: 0.55; }
.entry.status-done .entry-name { text-decoration: line-through; }
```

`#roadmap` is already `flex: 1`, so give its parent `display: flex` if it is
not already — check before adding, and do not duplicate a rule that exists.

- [ ] **Step 6: Run the tests, then prove one discriminates**

Run: `uv run pytest tests/test_roadmap.py -q`

Remove the `.filter((p) => !p.isolated)`. Run
`test_isolated_projects_leave_the_graph`. Paste the failure. Revert.

- [ ] **Step 7: Commit**

```bash
git add -A src/armoire/static tests/
git commit -m "feat: a category column for unconnected projects; delete the rail"
```

---

## Task 10: The root path breadcrumb

**Files:**
- Modify: `src/armoire/static/app.js`, `src/armoire/static/index.html`, `src/armoire/static/app.css`
- Test: `tests/test_navigation.py`

**Interfaces:**
- Consumes: `root` from `/api/projects`, which `app.py` already returns.
- Produces: `#root-name` holds the served path; the breadcrumb's first crumb is
  one element carrying `data-root`.

`/api/projects` is fetched only on the roadmap route, so the root must be
fetched independently. Add `root` to `/api/tree`'s response — it is fetched on
every browse route and already knows it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_navigation.py — append
def test_the_breadcrumb_root_shows_the_served_path(live_server, page, sample_root):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    shown = page.locator("#breadcrumb [data-root]").inner_text()
    assert shown == str(sample_root).replace("\\", "/")


def test_the_root_crumb_is_one_element_not_a_trail(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    assert page.locator("#breadcrumb [data-root]").count() == 1


def test_clicking_the_root_crumb_goes_to_the_root_listing(live_server, page):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector("#breadcrumb [data-root]")
    page.locator("#breadcrumb [data-root]").click()
    page.wait_for_url("**/#/browse/")


def test_double_clicking_the_root_crumb_returns_to_the_roadmap(live_server, page):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector("#breadcrumb [data-root]")
    page.locator("#breadcrumb [data-root]").dblclick()
    page.wait_for_selector(".node")
    assert page.locator("#roadmap").is_visible()


def test_a_folder_with_no_registry_says_the_gesture_is_inert(bare_server, page):
    page.goto(f"{bare_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    crumb = page.locator("#breadcrumb [data-root]")
    assert "no roadmap" in (crumb.get_attribute("title") or "").lower()
```

`bare_server` is the existing fixture for a folder with no registry — see
`tests/conftest.py:193`. Do not add a new one.

Note that Task 3 changed where the registry lives, so `bare_root` is now "a
folder whose *store* has no registry". Confirm `bare_server` still produces
that state after Task 3's rewiring; if `prepare_store` has since created a stub
for it, the fixture needs the stub suppressed rather than the test weakened.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_navigation.py -q -k "root_crumb or breadcrumb_root or double_click"`
Expected: FAIL — no `[data-root]` element.

- [ ] **Step 3: Implement**

`app.py`'s `/api/tree` gains `"root": str(root)` and
`"has_registry": store.registry_path(root).is_file()` in its return dict. Add a
pytest assertion for both in `tests/test_app.py`.

In `app.js`, cache them on the first tree fetch and render the crumb:

```javascript
let rootLabel = null;
let hasRegistry = false;

function displayRoot(path) {
  // Forward slashes on every platform. Display only -- resolution stays
  // pathlib's job behind resolve_in_root, and this string is never sent back.
  return String(path).replace(/\\/g, '/');
}

function renderBreadcrumb(path) {
  breadcrumb.replaceChildren();
  const rootLink = document.createElement('a');
  rootLink.href = `#/${BROWSE}/`;
  rootLink.setAttribute('data-root', '');
  rootLink.textContent = rootLabel || 'armoire';
  rootLink.title = hasRegistry
    ? 'Click for the root listing, double-click for the roadmap'
    : 'Click for the root listing. This folder has no roadmap.';
  // One crumb, not a trail: "D:" and "GitHub" name places outside the served
  // root that armoire cannot show, so they must not look clickable.
  rootLink.addEventListener('dblclick', (event) => {
    event.preventDefault();
    if (hasRegistry) window.location.hash = '/';
  });
  breadcrumb.append(rootLink);
  ...
}
```

`tree.js`'s `fetchDir` already returns the parsed body; have `initTree` expose
the root from its first fetch, or fetch `/api/tree?path=` once in `app.js`
before the first `renderBreadcrumb`. Pick one; do not fetch it per navigation.

Set `#root-name` in the header from the same value.

- [ ] **Step 4: Run the tests, then prove one discriminates**

Run: `uv run pytest tests/test_navigation.py -q`

Remove the `dblclick` listener. Run
`test_double_clicking_the_root_crumb_returns_to_the_roadmap`. Paste the
failure. Revert.

- [ ] **Step 5: Commit**

```bash
git add src/armoire/static src/armoire/app.py tests/
git commit -m "feat: the breadcrumb root is the served path, and returns to the roadmap"
```

---

## Task 11: The tree divider

**Files:**
- Create: `src/armoire/static/divider.js`
- Modify: `src/armoire/static/index.html`, `src/armoire/static/app.css`, `src/armoire/static/app.js`
- Test: `tests/test_navigation.py`

**Interfaces:**
- Produces: `initDivider(handle, pane, root) -> void`

Clamped to 180–600px. Persisted at `armoire:divider:<root>` in `localStorage`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_navigation.py — append
def test_the_tree_has_no_horizontal_scrollbar(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    overflow = page.locator("#tree").evaluate("el => getComputedStyle(el).overflowX")
    assert overflow == "hidden"


def test_a_long_name_truncates_rather_than_widening_the_tree(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    assert page.locator("#tree").evaluate("el => el.scrollWidth <= el.clientWidth + 1")


def test_dragging_the_divider_widens_the_tree(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    before = page.locator("#tree").bounding_box()["width"]
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] > before + 50


def test_the_divider_refuses_to_go_below_its_minimum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(0, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] >= 180


def test_the_divider_refuses_to_go_above_its_maximum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(2000, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] <= 600


def test_the_divider_width_survives_a_reload(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    width = page.locator("#tree").bounding_box()["width"]
    page.reload()
    page.wait_for_selector("#divider")
    assert abs(page.locator("#tree").bounding_box()["width"] - width) < 2


def test_the_arrow_keys_move_the_divider(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    before = page.locator("#tree").bounding_box()["width"]
    page.locator("#divider").focus()
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    assert page.locator("#tree").bounding_box()["width"] > before


def test_dragging_the_divider_does_not_write_to_the_served_folder(live_server, page, sample_root):
    before = folder_snapshot(sample_root)
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    assert folder_snapshot(sample_root) == before
```

`folder_snapshot` is the module-level helper Task 5 extracted into
`tests/conftest.py`. Import it; do not write a fourth copy.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_navigation.py -q -k divider`
Expected: FAIL — no `#divider` element.

- [ ] **Step 3: Implement `divider.js`**

```javascript
// A pane width is how one person likes looking at one folder in one browser,
// so it stays in localStorage. Status is the opposite and lives on the server.

const MIN = 180;
const MAX = 600;
const STEP = 16;

function key(root) {
  return `armoire:divider:${root}`;
}

export function initDivider(handle, pane, root) {
  function apply(width, persist) {
    const clamped = Math.min(MAX, Math.max(MIN, width));
    pane.style.flex = `0 0 ${clamped}px`;
    handle.setAttribute('aria-valuenow', String(Math.round(clamped)));
    if (persist) {
      try {
        window.localStorage.setItem(key(root), String(Math.round(clamped)));
      } catch {
        // Quota or a privacy mode that blocks storage. The drag still applied.
      }
    }
    return clamped;
  }

  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-orientation', 'vertical');
  handle.setAttribute('aria-valuemin', String(MIN));
  handle.setAttribute('aria-valuemax', String(MAX));
  handle.tabIndex = 0;

  let saved = NaN;
  try {
    saved = Number(window.localStorage.getItem(key(root)));
  } catch {
    // Storage unavailable; fall through to the default width.
  }
  apply(Number.isFinite(saved) && saved > 0 ? saved : pane.getBoundingClientRect().width, false);

  let dragging = false;
  handle.addEventListener('pointerdown', (event) => {
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  handle.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    apply(event.clientX - pane.getBoundingClientRect().left, false);
  });
  handle.addEventListener('pointerup', (event) => {
    if (!dragging) return;
    dragging = false;
    handle.releasePointerCapture(event.pointerId);
    apply(pane.getBoundingClientRect().width, true);
  });
  // An interrupted gesture must not leave the handle stuck in drag mode.
  handle.addEventListener('pointercancel', () => { dragging = false; });

  handle.addEventListener('keydown', (event) => {
    const width = pane.getBoundingClientRect().width;
    if (event.key === 'ArrowRight') apply(width + STEP, true);
    else if (event.key === 'ArrowLeft') apply(width - STEP, true);
    else if (event.key === 'Home') apply(MIN, true);
    else if (event.key === 'End') apply(MAX, true);
    else return;
    event.preventDefault();
  });
}
```

- [ ] **Step 4: Wire it up**

`index.html`, between `#tree` and `#main`:

```html
  <div id="divider"></div>
```

`app.css`:

```css
#divider {
  flex: 0 0 5px;
  cursor: col-resize;
  background: var(--border);
  opacity: 0.5;
}
#divider:hover, #divider:focus { opacity: 1; outline: none; }
/* The divider is how you read a long name in full, so the pane no longer
   scrolls sideways and rows truncate instead. */
#tree { overflow-x: hidden; }
#tree .row span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
#tree .row { min-width: 0; }
```

Check `#tree`'s existing rule before adding `overflow-x` — edit it rather than
adding a competing declaration.

`tree.js`'s `makeRow` sets the name span's `title` to the label so the full
name is reachable on hover.

`app.js` calls `initDivider` once at startup, after the root is known:

```javascript
initDivider(document.getElementById('divider'), document.getElementById('tree'), rootLabel);
```

- [ ] **Step 5: Run the tests, then prove two discriminate**

Run: `uv run pytest tests/test_navigation.py -q`

Change `MIN` to `0`. Run `test_the_divider_refuses_to_go_below_its_minimum`.
Paste the failure. Revert.

Remove the `localStorage.setItem` call. Run
`test_the_divider_width_survives_a_reload`. Paste the failure. Revert.

- [ ] **Step 6: Full suite, lint, commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add -A src/armoire/static tests/
git commit -m "feat: a resizable tree divider, and no horizontal scrollbar"
```

---

## Task 12: Documentation and the real registry

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-08-01-armoire-roadmap-design.md`
- Create: `D:\GitHub\summer-26`'s store registry (outside this repo)

- [ ] **Step 1: Update the README**

Document the store: where it lives on each platform, that `serve` creates a
stub on first use, that a Phase 2 `armoire.toml` is migrated and the original
left in place, and that status is stored per folder rather than per browser.
Document the four status values and the `blocked_by`-or-`category` rule.

Do not claim `uvx armoire serve .` works — armoire is not on PyPI. The README
already says so; keep it accurate.

- [ ] **Step 2: Mark the Phase 2 spec superseded**

Add a line to `2026-08-01-armoire-roadmap-design.md`'s header noting that its
registry location is superseded by
`2026-08-02-armoire-phase3-design.md`, in the same form Phase 1's spec already
uses. Do not rewrite its body: it records what shipped at the time.

- [ ] **Step 3: Migrate the real registry**

Run `armoire serve D:/GitHub/summer-26` once and confirm it migrates the
existing `armoire.toml` into the store and prints the new path. Then edit the
store copy to apply the three corrections:

- `FINM 32000` gains `FINM 33000` in `blocked_by`.
- `quant-linalg`, `LeetCode`, `BUSN 41902` and `FINM 37400` all take
  `category = "Interview Prep"`.
- `BofA` and `XTech` keep `category = "internship"`.

Confirm the roadmap renders with the isolated projects in two category
containers and the graph starting hard left.

Leave `D:\GitHub\summer-26\armoire.toml` where it is. It is untracked in that
repo and deleting it is not this plan's business.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/
git commit -m "docs: the store, status, and the placement rule"
```

---

## Self-review notes

Checked against the spec:

- Store location, folder key, atomic write, store-inside-root refusal — Tasks 1, 3.
- `status` field, four values, invalid-value fallback — Task 2.
- `blocked_by`-or-`category` rule — Task 2.
- Isolation server-side, four shapes — Task 4.
- Effective status, registry as initial value — Task 4.
- `PUT /api/status` with header and origin guards — Task 5.
- Entries for removed projects kept, not pruned — Task 5.
- Wrapped variable-height nodes, no text outside the rect, badge removed — Task 6.
- Status border, blocked fill, done-blocker edge style — Task 7.
- Chip cycles, does not open the detail, keyboard-reachable — Task 7.
- Status survives a fresh browser context — Task 7.
- `done` collapses — Task 7.
- Wheel zoom anchored at the cursor, `passive: false`, clamp — Task 8.
- `align: 'UL'` — Task 6, where `layout` is already being changed.
- Category column, `Uncategorised` fallback, rail deleted — Task 9.
- Registry issue count in the status strip — Task 9.
- Root crumb as one element, single and double click, inert with no registry — Task 10.
- Divider clamp, persistence, keyboard, no horizontal scrollbar — Task 11.
- Read-only test extended for the status edit — Task 5; for the divider — Task 11.
