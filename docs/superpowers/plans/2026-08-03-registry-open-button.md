# Registry Open Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a button in armoire's browser UI that opens the served folder's `registry.toml` in the user's own editor, with the file path as a fallback when the launch fails.

**Architecture:** The registry lives in the per-user store, at a path containing eight hex characters of a SHA-256 — unreachable by hand. The browser cannot navigate to `file://` from an `http:` origin, so the browser asks the server instead: `POST /api/registry/open` hands the path to the OS's registered handler (`os.startfile` / `open` / `xdg-open`). The endpoint reuses, verbatim, the four-check guard stack `PUT /api/status` already carries; that stack is extracted into a shared helper first so the two handlers cannot drift apart.

**Tech Stack:** Python 3.12+, FastAPI, Click, uv, pytest, Playwright (chromium). Frontend is vanilla ES modules — no build step, no framework.

**Spec:** [`docs/superpowers/specs/2026-08-03-armoire-registry-access-design.md`](../specs/2026-08-03-armoire-registry-access-design.md)

## Global Constraints

- **`serve` never writes to the served folder.** `tests/test_app.py::test_serving_never_writes_to_disk` snapshots every file's mtime and sha256 before and after exercising every endpoint. Any new endpoint goes inside that window.
- **Never launch a real editor in a test.** `store.open_in_editor` must be monkeypatched in every Python test that reaches the endpoint, and the route must be stubbed via `page.route` in every Playwright test that clicks the button. An unstubbed test spawns a GUI application on the developer's or CI machine.
- **Tooling:** `uv run pytest`, `uv run ruff check`, `uv run ruff format`. Never `pip`, `black`, or `flake8`.
- **Commit style:** `type: description` — `feat`, `fix`, `docs`, `refactor`.
- **Branch:** `feature/registry-open-button`, already created. Never commit to `main`.
- **Line length / formatting:** whatever `ruff format` produces. Run it before every commit.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/armoire/store.py` | Add `open_in_editor(path)` — the platform dispatch, beside the other things armoire does to its own directory | 1 |
| `src/armoire/app.py` | Extract `_guard`; add `POST /api/registry/open`; add `registry` to `/api/tree` root metadata | 2, 3, 4 |
| `src/armoire/static/index.html` | Footer gains `<span id="status-text">` so the button can be a sibling | 5 |
| `src/armoire/static/app.css` | Footer becomes a flex row; button and fallback styling | 5, 6 |
| `src/armoire/static/app.js` | Repoint the `status` handle at the span; capture `rootMeta.registry`; mount the button in both places | 5, 6, 7 |
| `src/armoire/static/registry.js` | **New.** One module, one job: build the button, POST on click, degrade to path+copy on failure | 6, 7 |
| `tests/test_store.py` | `open_in_editor` platform dispatch and failure propagation | 1 |
| `tests/test_app.py` | Endpoint guards, happy path, 404, read-only refusal, tree payload, read-only sweep | 3, 4 |
| `tests/test_roadmap.py` | Playwright: button present, click, degraded state | 6, 7 |

---

### Task 1: `store.open_in_editor`

**Files:**
- Modify: `src/armoire/store.py` (append after `write_state`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `store.open_in_editor(path: Path) -> None`. Returns `None` on success; raises `OSError` when the launch fails. Never blocks.

**The gotcha that will bite you:** `os.startfile` **does not exist** on Linux or macOS. The implementation must therefore call it as `os.startfile(...)` (an attribute lookup at call time inside the `win32` branch), never `from os import startfile`, or the module fails to import on every non-Windows machine. The tests must patch it with `raising=False` for the same reason.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`:

```python
def test_open_in_editor_uses_startfile_on_windows(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    # raising=False: os.startfile does not exist on Linux or macOS, so on
    # every non-Windows machine this is creating the attribute rather than
    # replacing one. Without it, this test cannot run anywhere but Windows.
    monkeypatch.setattr(os, "startfile", lambda p: seen.append(p), raising=False)
    store.open_in_editor(target)
    assert seen == [target]


def test_open_in_editor_uses_open_on_macos(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: seen.append(argv))
    store.open_in_editor(target)
    assert seen == [["open", str(target)]]


def test_open_in_editor_uses_xdg_open_elsewhere(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: seen.append(argv))
    store.open_in_editor(target)
    assert seen == [["xdg-open", str(target)]]


def test_open_in_editor_never_waits_for_the_editor(tmp_path, monkeypatch):
    """A GUI editor outlives the request that launched it. Popen is started
    and abandoned; calling wait() would hang the handler for as long as the
    user keeps the file open."""
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")

    class Handle:
        def __init__(self):
            self.waited = False

        def wait(self, *a, **k):
            self.waited = True

    handle = Handle()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: handle)
    store.open_in_editor(target)
    assert not handle.waited


def test_open_in_editor_propagates_a_launch_failure(tmp_path, monkeypatch):
    """No handler registered, or no xdg-open on the box. The endpoint turns
    this into a 500 the UI can show, so it must not be swallowed here."""
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")

    def boom(argv):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", boom)
    with pytest.raises(OSError):
        store.open_in_editor(target)
```

Check the top of `tests/test_store.py` for the imports these need — `os`, `sys`, `pytest`, and `store`. Add whichever are missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py -k open_in_editor -v`
Expected: FAIL, `AttributeError: module 'armoire.store' has no attribute 'open_in_editor'`

- [ ] **Step 3: Write the implementation**

Add `import subprocess` to the imports at the top of `src/armoire/store.py` (it already imports `contextlib`, `hashlib`, `json`, `os`, `sys`, `tempfile`). Then append at the end of the file:

```python
def open_in_editor(path: Path) -> None:
    """Hand `path` to whatever the OS has registered for it. Never waits.

    A GUI editor outlives the request that launched it, so nothing here
    waits on the child: Popen is started and abandoned. Waiting would pin
    the handler thread for as long as the user keeps the file open.

    os.startfile is looked up on `os` at call time rather than imported at
    module scope, because it exists only on Windows -- a module-level
    `from os import startfile` would make this whole module unimportable on
    Linux and macOS.

    The default verb, not "edit": `edit` is frequently unregistered for
    .toml and raises where the default verb succeeds.

    Failures raise OSError (FileNotFoundError for a missing xdg-open,
    OSError for a Windows association failure). The caller translates.
    """
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - fixed path, no shell, no user input
        return
    launcher = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([launcher, str(path)])  # noqa: S603
```

If `ruff` does not flag those lines, drop the `noqa` comments — an unused `noqa` is itself a lint error under `RUF100`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py -k open_in_editor -v`
Expected: 5 passed

Then the whole store suite, to be sure the new import broke nothing:
Run: `uv run pytest tests/test_store.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/store.py tests/test_store.py
uv run ruff check src/armoire/store.py tests/test_store.py
git add src/armoire/store.py tests/test_store.py
git commit -m "feat: store.open_in_editor hands a path to the OS handler"
```

---

### Task 2: Extract the guard stack out of `set_status`

**Files:**
- Modify: `src/armoire/app.py:242-287` (the guard block inside `set_status`)
- Test: none new — this is a pure refactor, proven by the existing guard tests staying green.

**Interfaces:**
- Consumes: nothing.
- Produces: `_guard(request: Request, writes_into_root: bool) -> None`, module-level in `app.py`. Returns `None` when the request is allowed; raises `HTTPException(403)` otherwise. Task 3 calls it.

This task changes no behaviour. The four checks keep their order and their exact `detail` strings, because `tests/test_app.py` asserts on the resulting 403s and `test_the_host_allowlist_covers_all_loopback_forms_and_refuses_a_foreign_one` asserts the accept/reject split across four host spellings.

- [ ] **Step 1: Run the existing guard tests and record that they pass**

Run: `uv run pytest tests/test_app.py -k "refused or allowlist or foreign or rebound or store_inside" -v`
Expected: all pass. This is the baseline the refactor must preserve — if any of these are already failing, stop and say so rather than refactoring on top of a red suite.

- [ ] **Step 2: Add the module-level helper**

Insert into `src/armoire/app.py` immediately above `def create_app(root: Path) -> FastAPI:`. Move the whole comment block from inside `set_status` onto this function — do not leave a copy behind.

```python
def _guard(request: Request, writes_into_root: bool) -> None:
    """Refuse a state-changing request that is not our own page talking to us.

    Shared by every handler with a side effect, so the argument below lives
    in exactly one place. Two handlers carrying their own copies of a
    security check is how the two copies drift apart.

    The bind address stops other machines, not other tabs: any page in any
    browser on this machine can reach 127.0.0.1. What actually keeps a
    script on a foreign origin out is that neither PUT nor POST with a
    custom header is a CORS "simple request": the browser must preflight
    with OPTIONS first, armoire answers no CORS headers and installs no CORS
    middleware, so the preflight fails closed and the real request is never
    sent. X-Armoire is belt-and-braces on top of that, not the sole barrier
    -- it also closes the HTML-form-post route in, since a form cannot set a
    custom header at all.

    The Origin check is a same-origin *self-consistency* check, not an
    allowlist: request.base_url is derived from this same request's own Host
    header, so "Origin equals base_url" holds tautologically for a request
    whose Host has been DNS-rebound to 127.0.0.1 -- the browser considers
    that request same-origin, sends no preflight, and lets script set
    X-Armoire freely. That is a real bypass of both checks at once, so the
    Host header itself is pinned to a fixed loopback allowlist here,
    independent of anything the request claims about its own Origin or Host.

    `writes_into_root` is decided at creation time, with the paths it
    protects, rather than re-asked here: it is fixed for an app's lifetime,
    so whether armoire's own writes land inside the served folder is fixed
    too. The question is about that write target and not about
    config_root() as a whole -- serving a descendant of config_root() puts
    the store directory inside root even though config_root() is not inside
    root, and a handler would then write into the tree it is serving.
    """
    if request.headers.get("X-Armoire") != "1":
        raise HTTPException(status_code=403, detail="missing X-Armoire header")
    # request.url.hostname, not a hand-split Host header: a bracketed IPv6
    # literal ("[::1]:8420") contains colons of its own, so splitting on ":"
    # takes the wrong piece and a genuine IPv6-loopback request would be
    # refused. The URL parser already strips the brackets, so the bracketed
    # spelling never appears in the allowlist itself -- only the unwrapped
    # "::1" does.
    host = request.url.hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(status_code=403, detail="foreign host")
    origin = request.headers.get("Origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="foreign origin")
    if writes_into_root:
        raise HTTPException(
            status_code=403, detail="the armoire store is inside the served folder"
        )
```

- [ ] **Step 3: Replace the inline block in `set_status` with the call**

In `set_status`, delete everything from the `# The bind address stops other machines…` comment down to and including the `raise HTTPException(status_code=403, detail="the armoire store is inside the served folder")` block — that is the whole span from line 242 to line 287. Put this in its place, as the first statement of the handler body:

```python
        _guard(request, writes_into_root)
```

The handler then continues, unchanged, at `status = payload.get("status")`.

- [ ] **Step 4: Run the guard tests to verify they still pass**

Run: `uv run pytest tests/test_app.py -k "refused or allowlist or foreign or rebound or store_inside" -v`
Expected: same passes as Step 1 — identical count, no new failures.

Then the whole app suite:
Run: `uv run pytest tests/test_app.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/app.py
uv run ruff check src/armoire/app.py
git add src/armoire/app.py
git commit -m "refactor: extract the request guard out of set_status"
```

---

### Task 3: `POST /api/registry/open`

**Files:**
- Modify: `src/armoire/app.py` (new handler after `set_status`; sweep test update)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `_guard(request, writes_into_root)` from Task 2; `store.open_in_editor(path)` from Task 1.
- Produces: `POST /api/registry/open` → `200 {"opened": true}`. Task 6's frontend calls it.

**Known and accepted:** a folder whose registry file does not exist yet gets a 404. In real use `cli.prepare_store` writes a stub before the server starts, so this is reachable only if the file is deleted underneath a running server, or in a test fixture that bypasses the CLI. The frontend's degraded state shows the path, which is the useful answer in that case anyway.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`. `_client_with_registry`, `HEADERS`, and `REGISTRY` already exist in that file — reuse them, do not redefine them.

```python
def test_opening_the_registry_launches_the_os_handler(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    client = _client_with_registry(tmp_path)
    response = client.post("/api/registry/open", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {"opened": True}
    assert seen == [store.registry_path(tmp_path)]


def test_opening_the_registry_without_the_header_is_refused(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    client = _client_with_registry(tmp_path)
    response = client.post("/api/registry/open")
    assert response.status_code == 403
    # The refusal must happen before the launch, not after it.
    assert seen == []


def test_opening_the_registry_from_a_foreign_origin_is_refused(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    client = _client_with_registry(tmp_path)
    response = client.post(
        "/api/registry/open", headers=HEADERS | {"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert seen == []


def test_opening_the_registry_from_a_rebound_host_is_refused(tmp_path, monkeypatch):
    """The same DNS-rebinding case /api/status is pinned against: Origin
    equal to base_url holds tautologically once the Host is rebound, so the
    Host itself must name a real loopback address."""
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    client = _client_with_registry(tmp_path)
    response = client.post(
        "/api/registry/open",
        headers=HEADERS | {"Host": "evil.example", "Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert seen == []


def test_opening_a_registry_that_does_not_exist_is_404(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    (tmp_path / "docs").mkdir(exist_ok=True)
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post("/api/registry/open", headers=HEADERS)
    assert response.status_code == 404
    assert seen == []


def test_a_store_inside_the_served_folder_refuses_the_registry_open(tmp_path, monkeypatch):
    """Same shape as the status-write refusal: root is a *descendant* of
    config_root(), so the weaker "is config_root() inside root" predicate is
    False here and would let this through."""
    seen = []
    monkeypatch.setattr(store, "open_in_editor", lambda p: seen.append(p))
    config_root = tmp_path / "store"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    registry_file = store.registry_path(served)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(REGISTRY, encoding="utf-8")

    client = TestClient(create_app(served), base_url="http://127.0.0.1")
    response = client.post("/api/registry/open", headers=HEADERS)
    assert response.status_code == 403
    assert seen == []


def test_a_launch_failure_is_reported_rather_than_swallowed(tmp_path, monkeypatch):
    def boom(path):
        raise OSError("no application is associated with .toml")

    monkeypatch.setattr(store, "open_in_editor", boom)
    client = _client_with_registry(tmp_path)
    response = client.post("/api/registry/open", headers=HEADERS)
    assert response.status_code == 500
    assert "no application" in response.json()["detail"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k registry_open -v`
Expected: FAIL with 405 Method Not Allowed (the static mount answers the path, the route does not exist yet).

- [ ] **Step 3: Write the implementation**

Add to `src/armoire/app.py`, immediately after the `set_status` handler and before `app.mount("/", StaticFiles(...))`:

```python
    @app.post("/api/registry/open")
    def open_registry(request: Request) -> dict:
        """Hand registry.toml to the user's own editor.

        POST, not GET: this has a side effect, and a GET is reachable from a
        foreign page through <img src>, which sends no custom headers and
        would sail past the X-Armoire check. _guard's argument assumes a
        method the browser must preflight.

        The path is `registry_file`, resolved once at create_app time. No
        request data reaches the launcher -- there is nothing here for a
        caller to point at a file of their choosing.
        """
        _guard(request, writes_into_root)
        if not registry_file.is_file():
            # cli.prepare_store writes a stub before the server starts, so
            # this is reachable only if the file is removed underneath a
            # running server. The client shows the path when this comes
            # back, which is the useful answer for a file that should exist
            # and does not.
            raise HTTPException(status_code=404, detail="no registry")
        try:
            store.open_in_editor(registry_file)
        except OSError as exc:
            # No handler registered for .toml, or no xdg-open on the box.
            # The message is the only thing that distinguishes "nothing is
            # installed" from "armoire is broken", so it travels to the UI.
            logger.warning("could not open the registry: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from None
        return {"opened": True}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k registry_open -v`
Expected: 7 passed

- [ ] **Step 5: Put the endpoint inside the read-only window**

`test_serving_never_writes_to_disk` is the test that enforces armoire's central promise. A new write-capable surface outside its window is a surface nothing checks.

In `tests/test_app.py`, change the signature:

```python
def test_serving_never_writes_to_disk(root, monkeypatch):
```

Immediately after the existing `status = client.put(...)` line, add:

```python
    # The launcher is stubbed: this test must never spawn a real editor. What
    # is being measured is that reaching the endpoint -- guard, existence
    # check, dispatch -- touches nothing in the served folder.
    monkeypatch.setattr(store, "open_in_editor", lambda p: None)
    opened = client.post("/api/registry/open", headers=HEADERS)
```

and add this to the block of assertions below it, beside `assert status.status_code == 200`:

```python
    assert opened.status_code == 200, opened.text
```

- [ ] **Step 6: Run the read-only sweep**

Run: `uv run pytest tests/test_app.py::test_serving_never_writes_to_disk -v`
Expected: PASS

Then the whole suite:
Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format src/armoire/app.py tests/test_app.py
uv run ruff check src/armoire/app.py tests/test_app.py
git add src/armoire/app.py tests/test_app.py
git commit -m "feat: POST /api/registry/open launches the registry in the user's editor"
```

---

### Task 4: Carry the registry path in `/api/tree` root metadata

**Files:**
- Modify: `src/armoire/app.py:76-98` (the `tree` handler's `if path == ""` block)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `writes_into_root` (already a `create_app` local), `registry_file` (already a `create_app` local).
- Produces: `/api/tree?path=` response gains `registry: str | null`. Task 6's `app.js` reads it as `rootMeta.registry`.

The root-level branch of `/api/tree` is already the bootstrap: it carries `root` and `has_registry`, and `tree.ready` in `app.js` consumes it exactly once at page load. One more field there costs nothing and needs no new fetch.

`null` when the store is unusable — that is the one case where there is no registry to point at, so a single nullable field answers both "should there be a button" and "what does it open".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def test_the_root_tree_payload_carries_the_registry_path(tmp_path):
    client = _client_with_registry(tmp_path)
    payload = client.get("/api/tree", params={"path": ""}).json()
    assert payload["registry"] == str(store.registry_path(tmp_path))


def test_a_subdirectory_tree_payload_carries_no_registry_path(client):
    """Root metadata is root-only: nothing downstream refetches it per
    navigation, so computing it on every subdirectory expansion is waste."""
    payload = client.get("/api/tree", params={"path": "docs"}).json()
    assert "registry" not in payload


def test_the_registry_path_is_null_when_the_store_is_inside_the_served_folder(
    tmp_path, monkeypatch
):
    """No usable store means no registry and no button. One nullable field
    answers both questions."""
    config_root = tmp_path / "store"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    client = TestClient(create_app(served), base_url="http://127.0.0.1")
    payload = client.get("/api/tree", params={"path": ""}).json()
    assert payload["registry"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k "registry_path or registry path" -v`
Expected: FAIL with `KeyError: 'registry'` on the first test.

- [ ] **Step 3: Write the implementation**

In `src/armoire/app.py`, inside the `tree` handler's `if path == "":` block, after the existing `payload["has_registry"] = ...` line:

```python
            # The path, so the client can offer to open it and can show it
            # when opening fails. None when the store is unusable: there is
            # no registry in that case, so one nullable field answers both
            # "is there a button" and "what does it open".
            payload["registry"] = None if writes_into_root else str(registry_file)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k "registry_path or registry path" -v`
Expected: 3 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/app.py tests/test_app.py
uv run ruff check src/armoire/app.py tests/test_app.py
git add src/armoire/app.py tests/test_app.py
git commit -m "feat: /api/tree root metadata carries the registry path"
```

---

### Task 5: Make room in the footer

**Files:**
- Modify: `src/armoire/static/index.html` (the `<footer>` element)
- Modify: `src/armoire/static/app.js:13` (one line)
- Modify: `src/armoire/static/app.css:331-338` (`#status`)
- Test: none new — proven by the existing Playwright suite staying green.

**Interfaces:**
- Consumes: nothing.
- Produces: `#status` is now a flex row container; `#status-text` is the element that carries the message. Task 6 appends the button to `#status`.

`#status` is written six times with bare `status.textContent = '…'` (`app.js:140, 189, 242, 291, 305, 308`), each of which would destroy a child button. Rather than retargeting six call sites, repoint the single module-level handle: `status` becomes the span, and the button goes into the footer around it.

- [ ] **Step 1: Record the Playwright baseline**

Run: `uv run pytest tests/test_roadmap.py tests/test_navigation.py -v`
Expected: all pass. If anything is already red, stop and report it — do not restructure markup on top of a failing browser suite.

- [ ] **Step 2: Give the footer a text element**

In `src/armoire/static/index.html`, replace:

```html
<footer id="status"></footer>
```

with:

```html
<footer id="status"><span id="status-text"></span></footer>
```

- [ ] **Step 3: Repoint the module handle**

In `src/armoire/static/app.js`, replace line 13:

```js
const status = document.getElementById('status');
```

with:

```js
// The span, not the footer: every write below is `status.textContent = …`,
// which replaces all children. The footer also holds the registry button
// (registry.js), and a textContent write on the footer would delete it on the
// next navigation. The message owns the span; the footer owns the row.
const status = document.getElementById('status-text');
```

- [ ] **Step 4: Make the footer a row**

In `src/armoire/static/app.css`, replace the `#status` rule:

```css
#status {
  flex: 0 0 auto;
  padding: 6px 16px;
  color: var(--muted);
  font-size: 12px;
  background: var(--subtle);
  border-top: 1px solid var(--border);
}
```

with:

```css
#status {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 16px;
  color: var(--muted);
  font-size: 12px;
  background: var(--subtle);
  border-top: 1px solid var(--border);
}

/* Takes the slack so anything beside it (the registry button) sits hard
   right. A long path in the message truncates rather than pushing the
   button off the edge. */
#status-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 5: Run the browser suite to verify nothing regressed**

Run: `uv run pytest tests/test_roadmap.py tests/test_navigation.py -v`
Expected: identical passes to Step 1.

- [ ] **Step 6: Commit**

```bash
git add src/armoire/static/index.html src/armoire/static/app.js src/armoire/static/app.css
git commit -m "refactor: the footer message gets its own element"
```

---

### Task 6: The button

**Files:**
- Create: `src/armoire/static/registry.js`
- Modify: `src/armoire/static/app.js` (import; `registryPath` module state; mount in `tree.ready`)
- Modify: `src/armoire/static/app.css` (button styling)
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `POST /api/registry/open` (Task 3); `rootMeta.registry` (Task 4); `#status` as a flex row (Task 5).
- Produces: `mountRegistryButton(container, registryPath) -> HTMLButtonElement | null` exported from `registry.js`. Returns `null` and mounts nothing when `registryPath` is falsy. Task 7 calls it a second time, for the error box.

**Do not skip the route stub.** Every Playwright test that clicks this button must intercept `**/api/registry/open`. `live_server` is a real app; an unstubbed click launches a real editor on the machine running the tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_roadmap.py`:

```python
def test_the_registry_button_is_in_the_footer_on_the_roadmap(page, live_server):
    open_roadmap(page, live_server)
    button = page.locator("#status .registry-open")
    assert button.is_visible()
    assert button.inner_text() == "Edit registry"


def test_the_registry_button_is_in_the_footer_on_the_browse_view(page, live_server):
    """The browse view matters as much as the roadmap: a folder with only a
    stub registry is bounced out of the roadmap into the file browser, so a
    roadmap-only button would be missing exactly when it is needed to declare
    a first project."""
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree", state="visible", timeout=15000)
    assert page.locator("#status .registry-open").is_visible()


def test_clicking_the_registry_button_asks_the_server_to_open_it(page, live_server):
    calls = []

    def stub(route, request):
        # Never let this reach the real endpoint: it would launch an editor
        # on whatever machine is running the suite.
        calls.append(request.method)
        route.fulfill(status=200, json={"opened": True})

    page.route("**/api/registry/open", stub)
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    page.wait_for_timeout(300)
    assert calls == ["POST"]


def test_the_registry_button_sends_the_guard_header(page, live_server):
    """Without X-Armoire the server refuses. A button that always 403s is a
    button that never works."""
    seen = []

    def stub(route, request):
        seen.append(request.headers.get("x-armoire"))
        route.fulfill(status=200, json={"opened": True})

    page.route("**/api/registry/open", stub)
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    page.wait_for_timeout(300)
    assert seen == ["1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -k registry_button -v`
Expected: FAIL — the locator resolves to nothing, `is_visible()` returns False.

- [ ] **Step 3: Write `registry.js`**

Create `src/armoire/static/registry.js`:

```js
// The one way to reach registry.toml from the browser.
//
// The file lives in the per-user store, in a directory named with eight hex
// characters of a SHA-256 -- unique by construction and unmemorable by
// consequence. A `file://` link cannot help: browsers block navigation from
// an http: origin to file:, silently. So the server, which is a local process
// with the user's own permissions, does the opening.

// Replaces the button with the path when the launch fails -- no handler
// registered for .toml, no xdg-open on the box. Showing the path is the whole
// of the weakest option considered during design, kept as the fallback rather
// than the feature: the worst case still beats hunting for the hash by hand.
// Replaces rather than appends, because a button that just failed should not
// go on looking clickable.
function showPath(button, registryPath, reason) {
  const wrap = document.createElement('span');
  wrap.className = 'registry-fallback';

  const why = document.createElement('span');
  why.textContent = `Could not open it (${reason}) —`;

  const path = document.createElement('code');
  path.textContent = registryPath;

  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'registry-copy';
  copy.textContent = 'Copy';
  copy.addEventListener('click', async () => {
    // navigator.clipboard needs a secure context, and every browser counts
    // http://127.0.0.1 as one. No HTTPS, and no execCommand fallback, needed.
    try {
      await navigator.clipboard.writeText(registryPath);
      copy.textContent = 'Copied';
    } catch {
      // Clipboard permission denied. The path is already on screen and
      // selectable, so there is nothing further to offer.
      copy.textContent = 'Select it above';
      copy.disabled = true;
    }
  });

  wrap.append(why, path, copy);
  button.replaceWith(wrap);
}

// `registryPath` is null when armoire has no usable store for this folder
// (store.writes_inside), in which case there is no registry to open and no
// button to show.
export function mountRegistryButton(container, registryPath) {
  if (!registryPath) return null;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'registry-open';
  button.textContent = 'Edit registry';
  button.title = registryPath;
  button.addEventListener('click', async () => {
    // Disabled for the round trip: os.startfile returns immediately, but a
    // cold editor launch still takes a moment, and a second click would
    // launch a second copy.
    button.disabled = true;
    try {
      const response = await fetch('/api/registry/open', {
        method: 'POST',
        headers: { 'X-Armoire': '1' },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || response.statusText);
      }
      button.disabled = false;
    } catch (error) {
      showPath(button, registryPath, String(error.message || error));
    }
  });
  container.append(button);
  return button;
}
```

- [ ] **Step 4: Mount it in the footer**

In `src/armoire/static/app.js`, add to the imports at the top:

```js
import { mountRegistryButton } from './registry.js';
```

Add beside the other module state (near `let hasRegistry = false;` at line 30):

```js
// The absolute path to this folder's registry.toml, or null when armoire has
// no usable store for it. Set once, at boot, from the root tree payload.
let registryPath = null;
```

In the `tree.ready` handler, immediately after `hasRegistry = rootMeta.hasRegistry;`:

```js
    registryPath = rootMeta.registry;
    // The footer, not the roadmap: a folder with only a stub registry never
    // reaches the roadmap at all (see showRoadmap's fallback below), and the
    // registry is exactly what it needs to edit to get there.
    mountRegistryButton(document.getElementById('status'), registryPath);
```

- [ ] **Step 5: Style it**

Append to `src/armoire/static/app.css`, after the `#status-text` rule from Task 5:

```css
.registry-open,
.registry-copy {
  flex: 0 0 auto;
  padding: 2px 10px;
  color: var(--fg);
  font: inherit;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
}

.registry-open:hover:not(:disabled),
.registry-copy:hover:not(:disabled) { border-color: var(--muted); }
.registry-open:disabled,
.registry-copy:disabled { cursor: default; opacity: 0.6; }

.registry-fallback {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.registry-fallback code {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: all;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_roadmap.py -k registry_button -v`
Expected: 4 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/armoire/static/registry.js src/armoire/static/app.js src/armoire/static/app.css
git commit -m "feat: an Edit registry button in the footer"
```

---

### Task 7: The button in the parse-error box, and the degraded state

**Files:**
- Modify: `src/armoire/static/app.js:160-168` (`showRoadmapError`)
- Test: `tests/test_roadmap.py`

**Interfaces:**
- Consumes: `mountRegistryButton` (Task 6); `registryPath` module state (Task 6).
- Produces: nothing further.

A registry that does not parse is the moment the file most needs opening — the message names the line number, and the fix is three seconds away in an editor. Putting the button in the error box puts the fix next to the error.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py` has no fixture for a registry that fails to parse. Add one, beside `empty_registry_root` and `empty_registry_server`, following their shape exactly:

```python
@pytest.fixture(scope="session")
def broken_registry_root(tmp_path_factory, _isolated_store_session):
    """TOML that does not parse. load_registry raises RegistryError, the
    endpoint answers 200-with-error, and app.js renders the message in the
    red box -- the one screen where the registry most needs opening."""
    root = tmp_path_factory.mktemp("broken-registry")
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text('[[project]]\nname = "Unclosed\n', encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def broken_registry_server(broken_registry_root):
    app = create_app(broken_registry_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
```

Copy the `while not server.started` wait and the teardown from `empty_registry_server` verbatim — if that fixture's body differs from what is written above, follow the existing one rather than this transcription.

Then append to `tests/test_roadmap.py`:

```python
def test_the_error_box_carries_a_registry_button(page, broken_registry_server):
    page.goto(f"{broken_registry_server}/#/")
    page.wait_for_selector("#roadmap-message .error", timeout=15000)
    assert page.locator("#roadmap-message .error .registry-open").is_visible()


def test_a_failed_launch_falls_back_to_the_path(page, live_server):
    """No handler registered for .toml. The button is replaced by the path
    and a copy button -- the worst case still beats hunting for the hash."""
    page.route(
        "**/api/registry/open",
        lambda route: route.fulfill(
            status=500, json={"detail": "no application is associated with .toml"}
        ),
    )
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    fallback = page.locator("#status .registry-fallback")
    fallback.wait_for(timeout=5000)
    assert "no application is associated" in fallback.inner_text()
    assert page.locator("#status .registry-fallback code").inner_text().endswith("registry.toml")
    # Replaced, not appended: a button that just failed must not still look
    # clickable.
    assert page.locator("#status .registry-open").count() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_roadmap.py -k "error_box_carries or failed_launch" -v`
Expected: FAIL — no `.registry-open` inside the error box; no `.registry-fallback` after the click.

- [ ] **Step 3: Mount the button in the error box**

In `src/armoire/static/app.js`, in `showRoadmapError`, after `roadmapMessage.replaceChildren(box);`:

```js
  // A registry that does not parse is the one screen where the file most
  // needs opening: the message names the line, and the fix is one click and
  // three seconds away. `box.textContent` above created a text node; append
  // adds the button as its sibling rather than replacing it.
  mountRegistryButton(box, registryPath);
```

The `.error` box is a normal-flow block, so the button lands beneath the message. If it needs to sit apart from the text, add to `app.css`:

```css
#roadmap-message .error .registry-open { margin-top: 10px; }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_roadmap.py -k "error_box_carries or failed_launch" -v`
Expected: 2 passed

- [ ] **Step 5: Run everything**

Run: `uv run pytest -v`
Expected: all pass

Run: `uv run ruff check` and `uv run ruff format --check`
Expected: clean. If `format --check` complains, run `uv run ruff format` and re-stage.

- [ ] **Step 6: Update the README**

The README's "Status" section describes the registry and says `serve` "prints the path so you know where to edit it". Add one sentence after that paragraph:

```markdown
The roadmap and the file browser both carry an **Edit registry** button in the
footer, which opens that file in whatever application your system associates
with `.toml`. If nothing is associated, the button gives you the path instead.
```

- [ ] **Step 7: Commit**

```bash
git add src/armoire/static/app.js src/armoire/static/app.css tests/conftest.py tests/test_roadmap.py README.md
git commit -m "feat: the parse-error box offers to open the registry"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: endpoint and guards → Tasks 2–3; `_guard` extraction → Task 2; launcher and its three platform branches → Task 1; the `registry` payload field → Task 4; footer restructure → Task 5; `registry.js` and the footer mount → Task 6; error-box mount and the degraded state → Task 7; the clipboard secure-context note → Task 6, Step 3; testing → distributed across all seven, with the read-only sweep in Task 3, Step 5. The spec's "What this does not do" needs no task by definition.

**Type consistency.** `mountRegistryButton(container, registryPath)` is defined in Task 6 and called with the same two-argument shape in Task 7. `_guard(request, writes_into_root)` is defined in Task 2 and called with that signature in Task 3. `store.open_in_editor(path)` is defined in Task 1 and monkeypatched under that exact name in Tasks 3 and 7. `registryPath` is the module-level name in `app.js` throughout; `rootMeta.registry` is the wire name throughout.

**Two places the implementer should verify rather than trust this document:**
- Task 2's line range (`app.py:242-287`) is correct as of commit `16bc78d`. Confirm the block still ends at the `writes_into_root` raise before deleting.
- Task 7's `broken_registry_server` fixture body is transcribed from `empty_registry_server`. Copy the real one; if the two differ, the real one wins.
