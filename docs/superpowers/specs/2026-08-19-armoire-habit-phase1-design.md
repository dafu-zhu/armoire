# Habit Phase 1 design

## Decision

Habit is a reserved use of the existing project category:

```toml
[[project]]
name = "Writing Practice"
paths = ["habits/writing"]
blocked_by = ["Writing Course"]
category = "habit"
```

No `[[habit]]` table or parallel persistence model exists. Arbitrary non-Habit
categories remain valid.

## Semantics

For an ordinary project, `blocked_by` declares roadmap topology. For a Habit, it
declares readiness gates:

- no gates: ready immediately;
- all known gates have effective status `done`: ready;
- any incomplete or unknown gate: locked.

Effective status respects the per-user `state.json` override before the registry
default. Unknown names retain the existing attributable registry issue and appear
in the locked-gate list.

`/api/projects` derives `is_habit`, `habit_unlocked`, and `habit_locked_by` on
read. None is persisted.

## Topology invariant

Habit nodes and gates never enter dagre. They do not create nodes, edges, ranks,
saved positions, or connectivity for ordinary projects. Ordinary-project
`isolated` classification uses only edges whose two ends are ordinary projects.
An ordinary project that names a Habit as a blocker receives an attributable
registry issue; that invalid edge is not drawn. The roadmap renderer also rejects
Habit rows defensively.

## Interface

Habits use the existing right category column under **HABIT**. Cards retain the
existing category colour, shape, note, issue marker, quick-look action, and
double-click folder navigation. Their state line reads `Ready` or
`Locked · <remaining gates>`.

Habit cards and their quick-look panel do not show or mutate the ordinary
not-started/active/paused/done lifecycle. Locking is guidance, not access control;
locked Habit paths remain navigable.

## Safety and compatibility

Registry and status state remain in Armoire's per-user store. Habit rendering and
navigation do not write to the served folder. Registries without `category =
"habit"` retain their existing graph, category cards, lifecycle controls, and
navigation.

## Deferred

Cadence, daily or weekly completion, streaks, history, reminders, scheduling,
domain-specific workflows, external data, and supporting methodology are outside
Phase 1.
