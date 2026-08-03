# armoire registry access — design

**Date:** 2026-08-03
**Status:** Approved. Builds on
[`2026-08-02-armoire-phase3-design.md`](2026-08-02-armoire-phase3-design.md),
which moved the registry into the per-user store. Nothing in that spec is
superseded; this one closes a gap it opened.

## Problem

Phase 3 moved the registry out of the served folder and into the store, so that
describing a folder never means modifying it. That was the right call, and it
cost something: the file is now at

```
%APPDATA%\armoire\folders\summer-26-74c70453\registry.toml
```

which nobody can reach without help. The directory name carries eight hex
characters of a SHA-256 that exists to make the name unique, not memorable.
`serve` prints the path once at startup (`cli.prepare_store`), and it scrolls
away. Nothing in the browser UI ever shows it.

So the file you must edit to get a roadmap at all is the one file armoire
gives you no way to open.

## Scope

**In:** a button in the browser that opens `registry.toml` in whatever
application the OS associates with it, plus the path itself as a fallback when
that fails.

**Out:** editing the registry inside armoire (Phase 3 ruled this out and this
spec does not revisit it); watching the file to auto-refresh the roadmap after a
save; a CLI subcommand; revealing the containing folder rather than the file.

## Approach

Three routes were considered.

**A `file://` link in the page.** Rejected — Chrome and Firefox both block
navigation from an `http:` origin to `file:`, with no workaround.

**A CLI subcommand (`armoire registry . --open`).** Rejected for now. It adds no
server surface, but the moment you want this you are in the browser, not at a
prompt. Cheap to add later if it earns its place.

**A server endpoint the browser calls, which launches the OS handler.**
Chosen. The server is already a local process running with the user's own
permissions, so it can do what the browser is sandboxed from doing. It also
reuses a guard stack that already exists.

## Endpoint

`POST /api/registry/open` → `200 {"opened": true}`.

POST rather than GET, because the call has a side effect. A GET is reachable
from a foreign page through `<img src>`, which sends no custom headers and would
pass the `X-Armoire` check unchallenged.

### Guards

Four checks, in order, identical to those `PUT /api/status` already performs:

1. `X-Armoire: 1` present — closes the CORS-simple-request and HTML-form-post
   routes in, neither of which can set a custom header.
2. `request.url.hostname` in `{127.0.0.1, localhost, ::1}` — pins the Host
   against DNS rebinding, which would otherwise make the Origin check
   tautological.
3. `Origin`, when present, equal to `request.base_url` — a same-origin
   self-consistency check, not an allowlist.
4. `writes_into_root` false — refuses when the store sits inside the served
   folder.

These are currently written inline in `set_status` (`app.py:242-287`) beneath a
comment block explaining why each exists and what each does not accomplish
alone. **They move into one `_guard(request)` helper that both handlers call,
and the comment block moves with them.** Two handlers carrying duplicate copies
of a security argument is how the two copies drift apart.

The path passed to the launcher is `registry_file`, resolved once at
`create_app` time. No request data reaches it.

### Failure modes

| Condition | Response |
|---|---|
| Guard 1–3 fails | 403, matching `set_status`'s existing details |
| Store inside served folder | 403 `the armoire store is inside the served folder` |
| Registry file absent | 404 `no registry` |
| Launcher raises `OSError` | 500 carrying the OS message |

## Launcher

A new function in `store.py`, beside the other things armoire does to its own
directory:

```python
def open_in_editor(path: Path) -> None:
    """Hand `path` to the OS's registered handler. Never waits for it."""
```

- **win32** — `os.startfile(path)`. The default verb, not `"edit"`: `edit` is
  frequently unregistered for `.toml` and raises where `open` succeeds.
- **darwin** — `subprocess.Popen(["open", str(path)])`.
- **otherwise** — `subprocess.Popen(["xdg-open", str(path)])`.

Never `wait()`: a GUI editor outlives the request that launched it, and waiting
would hang the handler for as long as the editor stays open. Failures raise
`OSError`, which the endpoint translates.

## Payload

`/api/tree?path=` already returns root metadata — `root` and `has_registry` —
on the root-level fetch only, and `tree.ready` consumes it exactly once at boot.
It gains one field:

```
registry: "C:\\Users\\...\\folders\\summer-26-74c70453\\registry.toml"  | null
```

`null` when `store.writes_inside(root)` — the store is unusable, so there is no
registry and no button. One field rather than two: when the store is unwritable
there is nothing to point at, so a single nullable path answers both "is there a
button" and "what does it open".

## Frontend

A new module, `registry.js`, exporting one button factory. `app.js` captures
`rootMeta.registry` at boot alongside `hasRegistry`, and mounts a button in two
places:

- **The footer**, present on both the roadmap and the browse view. The browse
  view matters as much as the roadmap: a folder with only a stub registry gets
  bounced out of the roadmap into the file browser (`app.js:203`), so a
  roadmap-only button would be missing exactly when you need it to declare your
  first project.
- **Inside `showRoadmapError`'s box**, where a parse failure is displayed. That
  is the moment the file most needs opening, and the message names the line.

Both mount points are skipped when `registry` is `null`.

### The footer restructure

`#status` is currently written with bare `status.textContent = '…'` assignments
in several places, each of which would destroy a child button. The footer gains
a `<span id="status-text">` for the message, with the button as its sibling, and
those assignments retarget to the span. This is the only change to existing
markup.

### Degraded state

When the POST fails, the button replaces itself in place with the path as
selectable text plus a copy button. That is the whole of the weakest option
considered during design — surface the path, let the user navigate — kept as the
fallback rather than the feature, so the worst case still beats today.

`navigator.clipboard` is available here: browsers treat `http://127.0.0.1` as a
secure context, so the copy button needs no HTTPS and no fallback of its own.

## Testing

- `open_in_editor`: each platform branch monkeypatched, asserting the right
  launcher receives the right path, and that `OSError` propagates. Nothing is
  ever spawned in CI.
- Endpoint: 403 with no `X-Armoire`; 403 on a foreign host; 403 when
  `writes_into_root`; 404 with the registry absent; 200 with the launcher called
  exactly once on the happy path.
- `/api/tree?path=` carries `registry`, and carries `null` when the store is
  unwritable.
- `test_serving_never_writes_to_disk` gains `/api/registry/open` in its endpoint
  sweep, launcher stubbed. Launching an editor must not write to the served
  folder, and that test is where the read-only guarantee is enforced — a new
  write-capable surface that sits outside its window is a surface nothing checks.
- Playwright: the button renders in the footer on both views and in the error
  box; a click with the POST stubbed calls it once; a stubbed failure renders the
  path and the copy button.

## What this does not do

The roadmap does not refresh when you save. You reload the page — the registry
is re-read on every request already (`load_registry` does a fresh `read_text`,
with no cache), so a reload is all it takes. Watching the file would mean a
watcher, a debounce, a push channel, and a reconciliation story for a graph the
user may have dragged out of its computed layout. That is a subsystem, and the
thing it saves is one keystroke.
