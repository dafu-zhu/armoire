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
        # Lead with a project name: issues are attributed to a node downstream
        # by splitting on the first ":", so a message starting with anything
        # else silently fails to mark the graph.
        issues.append(f"{cycle[0]}: dependency cycle via {' -> '.join(cycle)}")

    return Registry(projects=projects, issues=issues)
