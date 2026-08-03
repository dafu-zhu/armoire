"""The project registry.

The registry declares what a project is and what blocks it. Neither can be
inferred: a project may span several folders, and the dependency edges exist
only in the author's head. A tool that guesses structure is worse than one that
admits it does not know, so no registry means no roadmap.

The file itself lives in armoire's own store, outside the folder it describes
-- store.registry_path(folder), i.e. registry.toml under a per-folder
directory. Nothing here resolves that path: every production caller passes the
file to load_registry explicitly (app.create_app resolves it once, at creation
time). REGISTRY_NAME below is not that file. It is the Phase 2 filename, kept
only so cli.prepare_store can find a registry sitting in a served folder and
copy it into the store; once copied, the folder's own armoire.toml is never
read again.
"""

import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from armoire.paths import PathOutsideRoot, resolve_in_root

# The legacy filename to migrate *from*, not the file production reads. See
# the module docstring.
REGISTRY_NAME = "armoire.toml"
STATUSES = ("not-started", "active", "paused", "done")
# A project's status walks not-started -> active -> paused -> done; a project
# with no `status` field at all has not been picked up yet, which is the
# first of those, not the second.
DEFAULT_STATUS = "not-started"


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
    status: str = DEFAULT_STATUS


@dataclass
class Registry:
    projects: list[Project]
    issues: list[str] = field(default_factory=list)


def _as_str_tuple(value, field_name: str, project: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise RegistryError(f"{project}: {field_name} must be a list, not a string")
    if not isinstance(value, list | tuple):
        # A bare number or a table iterates to something -- or to nothing --
        # instead of raising here, so without this the TypeError escapes
        # load_registry raw and the endpoint 500s.
        raise RegistryError(f"{project}: {field_name} must be a list")
    return tuple(str(item) for item in value)


def _project_entries(raw: dict, path: Path) -> list:
    """The `project` key as a list of entries, or a RegistryError explaining it.

    `[project]` with one bracket is the most likely typo in the file and it is
    valid TOML, so it never reaches the TOMLDecodeError arm: it parses to a
    string-keyed table, and iterating that yields the *key names*. Checking only
    for "a list containing a non-dict" would miss it entirely.

    Labelled with `path`, the file actually read, rather than the constant
    REGISTRY_NAME ("armoire.toml"): once the registry lives in the store,
    that constant no longer names the file on disk at all (it is
    registry.toml, under a per-folder store directory), and on the migration
    path the served folder may hold a real, stale armoire.toml that armoire
    is deliberately ignoring -- naming that file here would send the user to
    edit the wrong one.
    """
    declared = raw.get("project", [])
    if isinstance(declared, dict):
        raise RegistryError(f"{path}: project must be declared as [[project]], not [project]")
    if not isinstance(declared, list):
        raise RegistryError(f"{path}: project must be a list of [[project]] tables")
    return declared


def _parse_project(entry, position: int) -> Project:
    if not isinstance(entry, dict):
        raise RegistryError(f"project #{position} is not a [[project]] table")
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
        status=entry.get("status", DEFAULT_STATUS),
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


def load_registry(root: Path, registry_file: Path | None = None) -> Registry | None:
    """Load the registry for `root`, or None when there is none.

    The registry is read from `registry_file`, which is where every production
    caller reads it from: the store, outside the served folder. `root` is only
    what `paths` resolve against. The `root / REGISTRY_NAME` fallback, for a
    caller that passes no file, is the Phase 2 location and survives for the
    convenience of tests that build a registry inside the folder they serve.

    Structural problems raise: a malformed file, an entry or field of the wrong
    shape, or a duplicate name means the graph cannot be trusted at all. Every
    such problem must raise `RegistryError` specifically -- app.py translates
    only that one, and anything else becomes a 500 with a text/plain body that
    the client cannot parse as JSON. Referential problems become issues: an
    unknown blocker or a missing folder still leaves a drawable graph, and
    reporting them beats refusing to render.
    """
    path = registry_file if registry_file is not None else root / REGISTRY_NAME
    if not path.is_file():
        return None

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise RegistryError(f"{path}: {exc}") from exc

    projects: list[Project] = []
    seen: dict[str, int] = {}
    for position, entry in enumerate(_project_entries(raw, path), start=1):
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
    for position, project in enumerate(projects):
        if project.status not in STATUSES:
            # An issue, not a raise: a typo in one optional field must not
            # remove the project from the graph.
            issues.append(
                f"{project.name}: unknown status {project.status!r}, using {DEFAULT_STATUS!r}"
            )
            projects[position] = replace(project, status=DEFAULT_STATUS)
        if not project.blocked_by and not project.category:
            # With neither, the project is in no graph and in no container:
            # there is nowhere on screen for it to be.
            issues.append(
                f"{project.name}: declares neither blocked_by nor category, so it cannot be placed"
            )
        for blocker in project.blocked_by:
            if blocker not in known:
                issues.append(f"{project.name}: blocked_by names unknown project {blocker!r}")
        for relative in project.paths:
            try:
                resolved = resolve_in_root(root, relative)
            except PathOutsideRoot:
                # Distinct from "does not exist": an escaping path may well
                # exist, and the old check silently accepted it. The project
                # then renders with no files and no explanation.
                issues.append(f"{project.name}: path {relative!r} escapes the served root")
                continue
            if not resolved.exists():
                issues.append(f"{project.name}: path {relative!r} does not exist")

    cycle = _find_cycle(projects)
    if cycle is not None:
        # Lead with a project name, followed by ": ". Downstream (roadmap.js's
        # `flagged` set and per-node tooltip, categories.js's entry-warn) tests
        # each issue against each project name with
        # `issue.startsWith(`${name}:`)`, so a message starting with anything
        # else silently fails to mark the graph. Every issue built above
        # follows the same shape. Note this is a prefix test, not a split on
        # the first ":" -- splitting would drop any project whose own name
        # contains one, which is a legal registry name.
        issues.append(f"{cycle[0]}: dependency cycle via {' -> '.join(cycle)}")

    return Registry(projects=projects, issues=issues)
