"""Composes registry, activity and directory listings into dashboard payloads.

app.py stays routing-only: these two functions are what its two roadmap routes
call. The composition needs three modules at once, which is exactly the kind of
thing that would otherwise accrete inside a route handler.
"""

from dataclasses import asdict
from pathlib import Path

from armoire import store
from armoire.activity import recent_commits
from armoire.paths import PathOutsideRoot
from armoire.projects import STATUSES, Registry, RegistryError, load_registry
from armoire.scanner import list_dir


def has_roadmap(root: Path, registry_file: Path) -> bool:
    """Whether double-clicking the breadcrumb root would land on a roadmap.

    Deliberately not `registry_file.is_file()`: app.js's showRoadmap takes
    the "no roadmap, back to the browser" exit on `data.registry === false ||
    !data.projects.length`, so a registry file that parses to zero
    [[project]] entries is just as roadmap-less, from the user's seat, as no
    file at all -- both must report False here or the double-click gesture
    would claim a roadmap exists and then silently bounce back to /browse/.
    A registry that fails to parse is different: /api/projects still renders
    an error card for it instead of bouncing, so that case reports True.
    """
    try:
        registry = load_registry(root, registry_file)
    except RegistryError:
        return True
    return registry is not None and bool(registry.projects)


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


def project_detail(root: Path, registry: Registry, name: str) -> dict | None:
    match = next((p for p in registry.projects if p.name == name), None)
    if match is None:
        return None

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
