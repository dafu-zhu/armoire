# armoire roadmap — design

**Date:** 2026-08-01
**Status:** Approved
**Supersedes:** the Phase 2 section of [`2026-08-01-armoire-design.md`](2026-08-01-armoire-design.md)

## Problem

Phase 1 shipped a file browser. Using it revealed that the folder is not the
interesting structure — the relationships between projects are, and those are
invisible.

Two things exist nowhere in a form you can look at:

**The dependency graph.** In the originating corpus, `finm330` blocks `finm320`,
`FINM 320` and `FINM 330` both gate `0DTE`, and `0DTE` gates the calibration
paper. That structure lives only as prose spread across a root README, a planner
ledger, and a research schedule. Reconstructing it means reading three documents
and holding the result in your head.

**What actually moved.** Every ledger records what was intended. None records
what happened. `git log` knows, and nothing surfaces it.

## What this builds

The entry screen becomes a draggable dependency roadmap over registered
projects, with a collapsible rail for activity and blocked counts. A node opens
a project detail; a file there opens the Phase 1 viewer unchanged.

The file browser is not removed. It stops being the front door.

## Scope

**In:** the project registry, the roadmap graph, the collapsible rail, project
detail pages, git-derived activity.

**Out:** editing the registry from the UI, status and deadlines as first-class
features, scaffolding, conformance checking, multi-root.

### What this cancels

The superseded spec made Phase 2 a template system driving scaffolding
(`armoire init`), validation (`armoire check`) and presentation from one
declaration. Those are dropped. That design was written before the viewer
existed and guessed at the need; using the tool showed the need was different.

The template survives, but only as a registry. It declares what a project is and
what blocks it, because neither can be inferred.

## The registry

`armoire.toml` at the folder root.

```toml
[[project]]
name = "0DTE"
paths = ["research/0dte"]
blocked_by = ["FINM 320", "FINM 330"]
category = "research"
due = 2026-08-17
note = "arXiv preprint"

[[project]]
name = "FX options theory"
paths = ["learning/finm37301", "bofa/repos/fxcarry"]
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Identity. `blocked_by` references it. A duplicate name is a load error naming both entries — silently keeping one would drop a node from the graph. |
| `paths` | yes | One or more folders. A project is a concept that points at paths, not a directory — `FX options theory` spans two. Two projects may name the same path; activity is then counted for both. |
| `blocked_by` | no | Names of projects that must finish first. Edges in the graph. |
| `category` | no | Drives node colour. Free-form; colours are assigned from a fixed palette in first-seen order. |
| `due` | no | A TOML local date, not a string. Rendered on the node. Not otherwise interpreted — no overdue logic, no sorting. |
| `note` | no | One line under the name. |

`blocked_by` references **names, not paths**, so a project spanning several
folders is still one node.

**With no `armoire.toml`, the roadmap does not appear** and armoire opens on the
file browser exactly as it does today. An empty graph would be worse than none.

## Screens

| URL | Screen |
|---|---|
| `#/` | Roadmap |
| `#/project/<name>` | Detail: blockers, what it unblocks, declared paths, recent commits, file list |
| `#/<path>` | The Phase 1 viewer, unchanged |

## The roadmap

Layered left-to-right, blockers before the blocked. Node colour comes from
`category`. Every node is the same size — a commit count badge sits in its
corner, because scaling nodes by activity would encode one number in an area and
read as importance rather than recency.

Drag any node anywhere. Pan and zoom the canvas. Positions persist in
`localStorage`, keyed by the served root's path, with a reset control.

**Nothing is written to the folder.** `serve` never writes, enforced by a test
that checksums every file before and after exercising every endpoint. Putting
layout in `localStorage` keeps that true. The cost is that positions do not
follow you to another machine, which is the right trade for a guarantee this
central.

### Rendering

`dagre` computes rank assignment and positions; armoire renders the SVG itself
and handles clicks and dragging with native pointer events.

Two alternatives were rejected. Reusing the already-vendored mermaid produces
static SVG with no drag support and awkward click targets — the work would go
into fighting it. Hand-rolling the layering reinvents dagre and gets edge
routing wrong to save 93 KB, which is negligible beside the 2.5 MB of mermaid
already vendored.

## Activity

`git log --since=30.days -- <path>` for each declared path. Measured at 1.17s
for six paths on the originating corpus, so it is computed once on the existing
background index thread rather than per request.

Submodules need their own `git -C <path> log` — the parent repository's log does
not see inside them, and the corpus has four. Paths with no git history fall
back to file mtimes.

## Modules

### Backend — `src/armoire/`

| File | Responsibility |
|---|---|
| `projects.py` | Parse and validate `armoire.toml`; resolve `blocked_by` into edges; detect cycles |
| `activity.py` | Commit counts and last-commit time per path, submodule-aware |

`app.py` gains two routes and no logic:

```
GET /api/projects        → {projects: [...], issues: [...]}
GET /api/project/<name>  → detail, recent commits, file listing
```

### Frontend — `src/armoire/static/`

| File | Responsibility |
|---|---|
| `roadmap.js` | dagre layout, SVG render, pointer drag, localStorage persistence |
| `rail.js` | Collapsible rail: projects ranked by 30-day commit count, the list of blocked projects with what each waits on, and any registry issues (unknown reference, cycle, missing path). Collapsed by default; state persists in `localStorage` alongside node positions. |
| `project.js` | Project detail view |

`app.js` gains two routes. `preview.js`, `tree.js`, `filter.js` and every
renderer are untouched.

## Error handling

| Condition | Response |
|---|---|
| Malformed `armoire.toml` | Roadmap replaced by a readable parse error naming the line; file browser still works |
| `blocked_by` names an unknown project | That project renders with a warning badge; listed in the rail |
| Dependency cycle | Detected at load, reported with the cycle path; the rest of the graph still draws |
| A declared path does not exist | Project renders with a warning badge |
| `git` unavailable | Activity omitted; everything else works |

No condition takes down the file browser.

## Testing

pytest covers registry parsing (valid, malformed, duplicate name, unknown
reference, cycle, missing path), activity extraction including a submodule, and
both endpoints.

Playwright covers: the roadmap renders the declared nodes and edges; dragging
moves a node and the position survives a reload; reset restores the computed
layout; the rail toggles; a node click reaches the detail; a file click reaches
the viewer; and a folder with no `armoire.toml` falls back to the browser.

The read-only assertion is extended to cover the two new endpoints.

## Decisions and their reasons

**The registry is a registry, not a schema.** The superseded design had one
declaration drive scaffolding, validation and presentation. Three consumers made
the format carry three jobs. Registration is the only job that turned out to be
needed.

**`blocked_by` references names.** Paths would break the moment a project spans
two folders, which one already does.

**Positions live in the browser.** The alternative — writing them back to
`armoire.toml` — would make `serve` write to the served folder and break the
guarantee that makes armoire safe to point at anything.

**No registry means no roadmap.** Inferring projects from top-level directories
would produce a plausible, wrong graph. A tool that guesses structure is worse
than one that admits it does not know.
