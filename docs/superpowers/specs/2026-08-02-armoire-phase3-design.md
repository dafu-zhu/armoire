# armoire Phase 3 — design

**Date:** 2026-08-02
**Status:** Approved. Builds on
[`2026-08-01-armoire-roadmap-design.md`](2026-08-01-armoire-roadmap-design.md),
which shipped as Phase 2. That spec's registry location is **superseded** by
the store described below; everything else in it remains current.

## Problem

Phase 2 shipped the roadmap and the first real use exposed six defects, four
gaps, and one wrong decision.

**Defects.** Descriptions render outside their boxes, because SVG `<text>` does
not wrap and nodes are a fixed `NODE_W × NODE_H`. Projects that participate in
no dependency float in the middle of the canvas, pushing the projects that do
participate off-centre and burying the roots. Zoom is buttons-only. The tree
pane carries a horizontal scrollbar. There is no way back to the roadmap once
you enter browse mode. The commit-count badge reports lifetime commits, which
says nothing useful.

**Gaps.** There is no way to record that a project is finished, so a roadmap of
a half-done year looks identical to one not started. Unconnected projects have
nowhere to live. The breadcrumb root says `armoire`, naming the tool rather
than the folder. The tree pane's width is fixed, so a long filename is simply
unreadable.

**The wrong decision.** Phase 2 put `armoire.toml` in the served folder. That
makes describing a folder require modifying it, which is precisely what a
read-only viewer promises not to do. A folder you do not own, or do not want to
add files to, cannot get a roadmap at all.

## Scope

**In:** a per-user store outside the served folder, project status with
in-canvas editing, wrapped variable-height nodes, category containers, wheel
zoom, root-anchored layout, removal of the activity rail, browse-pane root
path, roadmap return, resizable tree divider.

**Out:** editing the registry from the browser, multi-root, search over project
metadata, status history, dark theme.

## The store

armoire keeps its own data in the platform's user-config directory, and never
in the folder being served.

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\armoire` |
| macOS | `~/Library/Application Support/armoire` |
| Linux | `$XDG_CONFIG_HOME/armoire`, falling back to `~/.config/armoire` |

Each served folder gets a directory under `folders/`, named from the path's
tail plus eight hex characters of the SHA-256 of its absolute resolved path:

```
%APPDATA%\armoire\
  folders\
    summer-26-a3f19c48\
      registry.toml     projects, dependencies, categories
      state.json        status per project
```

The tail is for humans reading the directory; the hash is what makes the name
unique. Two folders with the same basename get different directories.

The hash is taken over `os.path.normcase(os.path.realpath(folder))`, so a path
that differs only in case or in symlink hops resolves to one directory on the
platforms where those are the same location.

### Creation

`serve` creates the folder directory and a commented `registry.toml` stub the
first time it serves a folder, prints the path, and continues. A folder with
only a stub has no projects, so the roadmap falls back to the file browser
exactly as before — the stub is an invitation, not a change in behaviour.

### Migrating a Phase 2 registry

A folder carrying `armoire.toml` from Phase 2 is copied into the store on first
serve, and armoire says so. The original is **not** deleted: removing it would
be a write to the served folder. It is simply no longer read, and the startup
message says which file is now authoritative so the two do not silently
diverge.

### The store must not be inside the served folder

Serving a folder that contains the store — a home directory, or `%APPDATA%`
itself — would make armoire write inside the tree it promises not to touch.
When the store path is inside the served root, armoire refuses to create or
update anything, serves read-only, and says why. The roadmap still renders from
an existing registry; only writes are refused.

## Read-only boundary

**`serve` never writes to the served folder.** That is the guarantee, unchanged
from Phase 1, and it stays enforced by the checksum-and-mtime snapshot test.

What changes is that armoire now writes at all. Every write goes to the store,
and only to the store: the registry stub, and status. The snapshot test is
extended to cover a status edit, so the new write path is inside the window
that proves the served folder is untouched.

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

`paths` stay relative to the served folder, as before, and still resolve
through `resolve_in_root`. Moving the registry out of the folder does not move
the path jail.

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

Isolation is computed server-side and published as `isolated: bool`, so it is
testable in pytest rather than only through the browser.

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
already handles and needs the same discipline: the click that lands on the chip
is consumed there and never reaches the node's handler.

Category-column entries carry the same chip with the same behaviour.

### Persistence

Status is written to `state.json` in the store, through a new endpoint. It is
**not** browser state: it follows the folder, not the browser, and survives
clearing site data or switching browsers.

`registry.toml`'s `status` is the initial value, used when `state.json` has no
entry for that project. Once edited, `state.json` wins and the registry's value
is not consulted again for that project.

An entry in `state.json` naming a project the registry no longer contains is
kept, not pruned. Renaming a project in the registry and renaming it back
should not silently lose its status.

`Reset layout` restores node positions only. It does not clear status: a layout
is a view preference and a status is a claim about the work.

### The write endpoint

`PUT /api/status` takes a project name and a status, validates the status
against the four known values, and writes `state.json`. An unknown project name
is a 404; an unknown status is a 400.

The server binds `127.0.0.1`, which means any page in any browser on this
machine can reach it. A write endpoint therefore needs more than the bind
address:

- The request must carry `X-Armoire: 1`. A cross-origin page cannot set a
  custom header without a successful CORS preflight, and armoire answers no
  preflight and installs no CORS middleware, so the browser refuses the request
  before it is sent. This also rules out HTML form posts, which cannot set
  headers at all.
- If `Origin` is present it must match the server's own origin.

Writes are last-write-wins. `state.json` is written whole, to a temporary file
in the same directory and then renamed, so an interrupted write cannot leave a
truncated file where a valid one was.

### What `done` changes

A `done` project **collapses** to a single title line: name, struck through,
plus its chip. Its note and due date are hidden. The node is dimmed.
Collapsing feeds a smaller height into dagre, so the layout reflows and
finished work stops consuming canvas.

**The warning marker is not hidden.** This paragraph originally listed it
alongside the note and the due date, and that was wrong on both counts.
Hiding it buys nothing the collapse is for: the collapse exists to stop
finished work consuming canvas *height*, and the marker shares the title row
with the chip at any height, so suppressing it reclaims no space. And it
costs the only readable account of a registry problem — "Removing the
activity rail" below makes the node's `!`, with the full text in its `title`,
the one place an issue is legible, with the status strip carrying nothing but
a count that names no project. A `done` project is also the likeliest to have
one: a path stops existing exactly when the work finishes and the folder is
archived. The marker therefore moves off the node's bottom-right corner and
onto the title row, immediately left of the chip, on every node — at
`NODE_MIN_H` the corner placement sat directly under the chip, same `x`, same
anchor, and the two glyphs overlapped.

A `done` project's **outgoing edges** render dashed and dimmed.

A project is **blocked** — the muted fill — only while at least one of its
blockers is not `done`. When the last blocker completes, the fill returns to
its full category colour. This is what makes the graph answer "what can I start
now?", which is the question it exists for.

A `done` node keeps its own status border regardless of what blocks it; a
finished project is not waiting on anything by definition.

Status affects presentation only. It never changes which edges exist and never
removes a node.

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

`rankdir: LR` with `align: 'UL'` puts rank 0 on the left and top-aligns each
rank's rows, but it does not by itself decide *which* projects land on rank 0.
With isolated projects moved to the category column, rank 0 is meant to be
exactly the set of projects nothing blocks — "align the unblocked ones left"
— and neither of dagre's rankers gets there on its own. The default,
`network-simplex`, minimises total edge length: a root whose only dependent
sits several ranks away has slack, and the ranker spends it by sliding that
root rightward, off the rank its blocker-free siblings sit on. `longest-path`
does not fix this either — despite the name, dagre's implementation of it
schedules every node as late as possible relative to a sink it can reach, not
as early as possible from a source, so a root with a short reach gets pushed
right the same way. (This surfaced on the real registry: `STAT 31450` and
`FINM 33000` block something one rank away and stayed pinned left; `STAT
31511` blocks only `Calibration paper`, three ranks away, and drifted one
rank right of them under both rankers.)

`layout()` (`static/roadmap.js`) closes that gap itself: every root — a
project with no drawn incoming edge — gets a high-weight (`100`, against the
default `1` on every real edge), one-rank (`minlen: 1`) edge to a shared,
invisible anchor node. Deviating from the rank that arrangement implies then
costs far more than any edge-length saving elsewhere in the graph could
offset, which is enough to force every root to the same rank regardless of
how far its own dependents reach. The edges point root → anchor, not anchor →
root, so the anchor only has to clear a rank the graph's real edges already
reach — pinning roots this way costs no extra rank of its own, and so no
extra width, on the real registry, though the more balanced left column can
still add height (the real registry's 3 ranks stayed 696px wide and grew from
632.5px to 847.5px tall gaining `STAT 31511` as a fourth rank-0 row). A
same-rank (`minlen: 0`) edge between two distinct nodes was tried first and
rejected: dagre's position phase does not give such an edge any points, and
the graph crashes when the coordinate system pass touches it later. The
anchor node and its pin edges are removed from the graph again before
`layout()` returns, so nothing downstream — rendering, positions, the edge
count — ever sees them.

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
flagged as a deviation. `recent_commits` stays — the detail view's commit list
is still useful — and keeps the `_resolve` path jail it shares. Code in
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

The served root reaches the frontend as a new field on an existing endpoint; no
new route.

A folder with no projects has no roadmap to return to. The double-click is
inert there, and the crumb's tooltip says so rather than leaving a dead gesture
unexplained.

### Divider

A thin draggable divider sits between the tree and the content pane, clamped to
180–600px. Its position persists in `localStorage`: it describes how you like
looking at this folder in this browser, not anything true about the folder.

The tree pane loses its horizontal scrollbar. Long names truncate with an
ellipsis and carry a `title`; the divider is how you read a name in full.

The divider is keyboard-operable — arrow keys move it, `Home`/`End` jump to the
limits — and carries `role="separator"` with its current and limit values.

Node positions likewise stay in `localStorage`, unchanged from Phase 2.

## Files

| Module | Change |
|---|---|
| `store.py` | new — config dir, folder key, registry and state paths, atomic state write |
| `projects.py` | load from the store; parse and validate `status`; require `blocked_by` or `category` |
| `dashboard.py` | publish `isolated` and effective `status`; drop the commit count |
| `activity.py` | delete what the rail's removal makes unreachable |
| `app.py` | `PUT /api/status`; publish the served root path |
| `cli.py` | create the stub, migrate a Phase 2 registry, print the store path |
| `static/roadmap.js` | wrapping, variable height, wheel zoom, status chip, done collapse |
| `static/categories.js` | new — the category column |
| `static/status.js` | new — cycle order, the `PUT` call, optimistic update and rollback |
| `static/tree.js` | truncation, no horizontal scroll |
| `static/divider.js` | new — drag, clamp, persist |
| `static/app.js` | root crumb, double-click to roadmap, wire the divider |
| `static/rail.js` | deleted |

## Testing

pytest covers the store's path resolution on all three platforms with the
environment monkeypatched, folder-key stability and collision behaviour, the
atomic state write, `status` parsing including the invalid-value fallback, the
`blocked_by`-or-`category` rule, and isolation for each of the four shapes (no
edges, incoming only, outgoing only, both).

The endpoint's guard is tested directly: a request without `X-Armoire` is
refused, one with a foreign `Origin` is refused, and the legitimate request
succeeds.

Playwright against a live server covers the frontend, as in Phase 2 — never by
asserting on JavaScript source text. Five behaviours get explicit tests because
each is a silent-regression risk:

- A wrapped note's bounding box is inside its node's rect.
- The divider refuses both limits and survives a reload.
- Cycling a chip to `done` drops the dependent's blocked fill, and survives a
  reload **in a fresh browser context** — which is what proves status is not
  browser state.
- Clicking a chip does not open the detail view.
- The four statuses render four distinct borders, and status and blocked-ness
  are independent — a node can be `active` and blocked, or `not-started` and
  ready, and each pair renders differently from the other three.

The read-only guarantee test is extended to cover a status edit and a divider
drag, the same way Phase 2 extended it to cover a node drag.

## Decisions and their reasons

**The registry moved out of the served folder.** Describing a folder should not
require modifying it. This also removes the awkwardness that a read-only viewer
asked you to add a file before it could do its most useful thing, and it means
armoire works on folders you cannot or should not write to.

**Status is server-side; positions and divider width are not.** Status is a
claim about the work and belongs to the folder — it should be the same in every
browser, and it should survive clearing site data. A node position and a pane
width describe how one person likes looking at one folder in one browser.
Putting them in the store would sync a preference nobody wants synced and give
two people editing one folder a fight over layout.

**Auto-create the stub rather than requiring a command.** One less thing to
learn, and the message at startup teaches the store's existence at the moment
it becomes relevant. The cost is a small directory per folder ever served,
which is acceptable for text files of a few hundred bytes.

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

**The config directory is resolved in `store.py` rather than by a
dependency.** It is three branches and two environment variables. Hand-rolling
keeps the dependency list short and, more usefully, makes the behaviour on each
of the six CI platform-version combinations something the suite asserts rather
than something a library promises.
