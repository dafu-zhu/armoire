# armoire Phase 3 — design

**Date:** 2026-08-02
**Status:** Approved. Builds on
[`2026-08-01-armoire-roadmap-design.md`](2026-08-01-armoire-roadmap-design.md),
which shipped as Phase 2 and remains current except where noted below.

## Problem

Phase 2 shipped the roadmap and the first real use exposed six defects and four
gaps.

**Defects.** Descriptions render outside their boxes, because SVG `<text>` does
not wrap and nodes are a fixed `NODE_W × NODE_H`. Projects that participate in
no dependency float in the middle of the canvas, pushing the projects that do
participate off-centre and burying the roots. Zoom is buttons-only. The tree
pane carries a horizontal scrollbar. There is no way back to the roadmap once
you enter browse mode. The commit-count badge on each node reports lifetime
commits, which says nothing useful.

**Gaps.** There is no way to record that a project is finished, so a roadmap of
a half-done year looks identical to one not started. Unconnected projects have
nowhere to live. The breadcrumb root says `armoire`, which names the tool
rather than the folder. And the tree pane's width is fixed, so a long filename
is simply unreadable.

## Scope

**In:** wrapped variable-height nodes, project status with in-canvas editing,
category containers for unconnected projects, wheel zoom, root-anchored layout,
removal of the activity rail, browse-pane root path, roadmap return, resizable
tree divider.

**Out:** editing anything that lives in `armoire.toml`, multi-root, search over
project metadata, status history, dark theme.

## Registry format

Two new rules and one new field.

```toml
[[project]]
name = "FINM 32000"
paths = ["learning/finm32000"]
blocked_by = ["STAT 31450", "FINM 33000"]
category = "course"
status = "active"          # new, optional
note = "Numerical methods."
```

**`status`** is one of `not-started`, `active`, `paused`, `done`. It is
optional and defaults to `active`. An unrecognised value is a registry issue
and falls back to `active` — a typo must not remove a project from the graph.

**Every project declares `blocked_by` or `category`.** A project with neither
cannot be placed: it is not in the graph and belongs to no container. That is a
registry issue naming the project. Both may be present; `category` also drives
node colour, as it already does.

### Placement

A project is **isolated** when nothing blocks it and it blocks nothing.

- **Isolated** projects leave the graph and group by `category` into the right
  column.
- **Everything else** stays in the graph, including projects with no
  `blocked_by` that block others — STAT 31450 and FINM 33000 are roots, not
  strays.

Isolation is computed server-side and published as `isolated: bool` on each
project, so it is testable in pytest rather than only through the browser.

An isolated project whose `category` is missing is already a registry issue; it
renders in an `Uncategorised` container so it is visible rather than dropped.

## Status

### How status reads

**Status is the node's border.** It must be legible across the whole canvas at
a glance, without reading any text, so it gets the strongest available channel:

| Status | Border |
|---|---|
| `not-started` | 1px dotted |
| `active` | 2.5px solid |
| `paused` | 1.5px dashed |
| `done` | 1px solid, dimmed |

That collides with Phase 2, which drew a heavy outline for *blocked*. Two
meanings cannot share one channel, so each moves to its own:

| Signal | Channel |
|---|---|
| status | border weight and dash |
| blocked or ready | fill saturation — blocked is muted, ready is the full category colour |
| blocker satisfied | edge style — dashed and dim from a `done` blocker, solid otherwise |

Readiness stays readable two ways: the node's own fill, and the fact that every
incoming edge has gone dashed.

### Editing

The status chip sits in each node's top-right corner, in the space the commit
badge vacates. It is the control, not the primary indicator — the border is
what you read, the chip is what you click. Clicking it cycles `not-started →
active → paused → done → not-started`. The chip is a focusable control with its
own `aria-label`, so the cycle is reachable from the keyboard.

The chip must not open the detail view. This is the same hazard the drag guard
already handles, and it needs the same discipline: the click that lands on the
chip is consumed there and never reaches the node's own handler.

Category-column entries carry the same chip with the same behaviour.

### Persistence

Status lives in `localStorage`, keyed by project name, in the same store family
as node positions. **`serve` still never writes to the served folder** — that
guarantee is unchanged and remains enforced by the checksum-and-mtime snapshot
test.

`armoire.toml`'s `status` is the initial value. A local edit overrides it and
keeps overriding it; the file is never consulted again for that project. The
override is per-browser and clearing site data resets it.

`Reset layout` restores node positions only. It does not clear status, because
the two have different lifetimes — a layout is a view preference and a status
is a claim about the work.

### What `done` changes

A `done` project **collapses** to a single title line: name, struck through,
plus its chip. Its note, due date and warning marker are hidden. The node is
dimmed. Collapsing feeds a smaller height into dagre, so the layout reflows and
finished work stops consuming canvas.

A `done` project's **outgoing edges** render dashed and dimmed.

A project is **blocked** — the muted fill — only while at least one of its
blockers is not `done`. When the last blocker completes, the fill returns to
its full category colour. This is what makes the graph answer "what can I start
now?", which is the question it exists for.

A `done` node keeps its own status border regardless of what blocks it; a
finished project is not waiting on anything by definition.

Status affects presentation only. It never changes which edges exist, never
removes a node, and never alters `armoire.toml`.

## Nodes

Node width stays fixed. Height varies.

The note is wrapped by a greedy word-wrap pass measured against the live SVG
with `getComputedTextLength`, into `<tspan>` lines at `NODE_W - 24`. Height
becomes header + line count × line height + padding, and that height is what
dagre lays out with, so edges still meet box edges. A single word longer than
the line box is broken rather than allowed to overflow.

**No text may render outside its node's rect.** This is the defect that
motivated the change and it is pinned by a test comparing the text's bounding
box against the rect's, not by eye.

The commit-count badge is removed.

## Layout

`rankdir: LR` with `align: 'UL'`, so rank 0 sits hard left and rows start at
the top. With isolated projects moved to the category column, rank 0 is exactly
the set of projects nothing blocks — which is what "align the unblocked ones
left" means.

### Zoom

The mouse wheel zooms, anchored at the cursor: the point under the pointer
stays under the pointer. The existing 35%–250% clamp and the existing buttons
are unchanged, and the on-screen percentage stays in sync.

The handler calls `preventDefault`, or the page scrolls behind the canvas. It
is registered `passive: false`, since a passive listener cannot prevent the
default and the browser will ignore the call.

## Category column

A permanent column on the right of the roadmap screen. One container per
category, coloured to match that category's node colour, holding its isolated
projects. Each entry shows name, status chip and note, and opens the project
detail on click.

The column appears on the roadmap screen only. Browse mode is unaffected.

## Removing the activity rail

The rail, its `Details` toggle, and `rail.js` are deleted. The right side of
the roadmap screen holds the category column and nothing else.

Three things the rail carried need to go somewhere:

- **Registry issues** keep the `!` marker on the node, which already carries the
  full text in a `title`. A count moves to the status strip, so a folder with
  problems still says so without opening anything.
- **The blocked list** is the graph.
- **The 30-day commit ranking** goes away with the rail. It has no other
  consumer once the node badge is gone.

That last removal deletes the per-request `activity_for` cost the Phase 2 spec
had flagged as a deviation. `recent_commits` stays — the detail view's commit
list is still useful — and keeps the `_resolve` path jail it shares. Code in
`activity.py` left unreachable by this change is deleted rather than kept.

## Browse pane

### Root breadcrumb

The root crumb shows the served folder's absolute path with forward slashes on
every platform: `D:/GitHub/summer-26`, `/home/me/notes`. Normalisation is
display-only and does not touch path resolution, which stays `pathlib`'s job
behind `resolve_in_root`.

The path is **one crumb, not a trail**. `D:`, `GitHub` and `summer-26` are not
separately clickable, because they name locations outside the served root that
armoire cannot show.

- **Single click** navigates to the root listing.
- **Double click** returns to the roadmap.

The served root reaches the frontend as a new field on an existing endpoint;
no new route.

A folder with no registry has no roadmap to return to. The double-click is
inert there, and the crumb's tooltip says so rather than leaving a dead
gesture unexplained.

### Divider

A thin draggable divider sits between the tree and the content pane, clamped to
180–600px. Its position persists in `localStorage`, alongside node positions
and status.

The tree pane loses its horizontal scrollbar. Long names truncate with an
ellipsis and carry a `title`; the divider is how you read a name in full.

The divider is keyboard-operable — arrow keys move it, `Home`/`End` jump to the
limits — and carries `role="separator"` with its current and limit values.

## Files

| Module | Change |
|---|---|
| `projects.py` | parse and validate `status`; require `blocked_by` or `category` |
| `dashboard.py` | publish `isolated` and `status`; drop the commit count |
| `activity.py` | delete what the rail's removal makes unreachable |
| `app.py` | publish the served root path |
| `static/roadmap.js` | wrapping, variable height, wheel zoom, status chip, done collapse |
| `static/categories.js` | new — the category column |
| `static/status.js` | new — status store, cycle order, localStorage |
| `static/tree.js` | truncation, no horizontal scroll |
| `static/divider.js` | new — drag, clamp, persist |
| `static/app.js` | root crumb, double-click to roadmap, wire the divider |
| `static/rail.js` | deleted |

## Testing

pytest covers `status` parsing including the invalid-value fallback, the
`blocked_by`-or-`category` rule, and isolation for each of the four shapes
(no edges, incoming only, outgoing only, both).

Playwright against a live server covers the rest, as in Phase 2 — never by
asserting on JavaScript source text. Four behaviours get explicit tests because
each is a silent-regression risk:

- A wrapped note's bounding box is inside its node's rect.
- The divider refuses both limits and survives a reload.
- Cycling a chip to `done` drops the dependent's blocked fill, and survives a
  reload.
- Clicking a chip does not open the detail view.
- The four statuses render four distinct borders, and status and blocked-ness
  are independent — a node can be `active` and blocked, or `not-started` and
  ready, and each pair renders differently from the other three.

The read-only guarantee test is extended to cover a status edit and a divider
drag, the same way Phase 2 extended it to cover a node drag.

## Decisions and their reasons

**Status in `localStorage`, not `armoire.toml`.** Writing the registry would
break the read-only guarantee, which is the project's load-bearing promise and
the thing a user trusts when pointing it at a folder they care about. The cost
is that status is per-browser. The toml keeps a `status` field so a shared
folder can ship a sensible starting state.

**Isolation computed server-side.** It is a pure function of the edge set the
frontend already holds, so either side could do it. Server-side makes it a
pytest assertion instead of a browser assertion, and this codebase has a
documented history of frontend tests that pass while asserting nothing.

**`done` collapses rather than hides.** Hiding finished work would silently
change the graph's shape and make a completed prerequisite look like a missing
one. Collapsing reclaims the space while keeping the node, its edges, and the
evidence that it was finished.

**The category column is permanent, not another toggle.** Phase 2's rail was
behind a toggle and the content behind it was rarely worth opening. Categories
are a permanent part of the picture: they are the projects with no place in the
graph, and hiding them by default would reproduce the problem this phase exists
to fix.
