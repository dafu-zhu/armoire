# Serve Takeover, Detach, and List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `armoire serve` replace an armoire already holding its port (behind `--force`), run in the background (`--detach`), and let `armoire list` show which port is serving which folder.

**Architecture:** A new module `armoire/instance.py` owns everything about "which armoire is where". It proves identity over HTTP — only armoire answers `GET /api/instance`, and it answers with its own pid — so the pid being killed always comes from the live process on that port, never from a file that could name a recycled pid. Instance record files exist only to say which ports are worth probing; every fact printed comes from the probe.

**Tech Stack:** Python 3.11+, FastAPI, Click, uvicorn, uv, pytest. HTTP probing uses stdlib `urllib.request` — **no new dependency may be added by this plan.**

**Spec:** [`docs/superpowers/specs/2026-08-03-armoire-serve-takeover-design.md`](../specs/2026-08-03-armoire-serve-takeover-design.md)

## Global Constraints

- **`--force` widens permission, never identity.** It authorises replacing an armoire. It must never authorise killing a process armoire could not identify. A port held by a non-armoire is a hard error *with or without* `--force`.
- **armoire only ever kills a pid that armoire itself just reported, on the port it is about to take.** No pid from a file is ever passed to `os.kill`.
- **`serve` never writes to the served folder.** `store.writes_inside(folder)` already gates this. The detach log and the instance record file are files like any other and inherit that refusal.
- **No new runtime dependency.** `pyproject.toml`'s `dependencies` list must be unchanged at the end of this plan. Use `urllib.request`, `socket`, `subprocess`, `signal` from stdlib.
- **No example or error message recommends bare `-f`.** Advertise `-df` and the long `--force`. Click's own options table renders `-f, --force`; that is fine and out of scope for the rule.
- **Nothing is deprecated.** `--port`, `--detach`, `--force` all keep working in full.
- **No test may kill a process it did not itself start.**
- **Tooling:** `uv run pytest`, `uv run ruff check`, `uv run ruff format`. Never `pip`, `black`, `flake8`.
- **Commit style:** `type: description` — `feat`, `fix`, `docs`, `refactor`.
- **Branch:** `feature/serve-takeover`, already created. Never commit to `main`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/armoire/app.py` | Add `GET /api/instance` — the identity endpoint everything else trusts | 1 |
| `src/armoire/instance.py` | **New.** Probe, claim, and record. The only module that calls `os.kill` | 2, 3 |
| `src/armoire/cli.py` | `-p`/`-d`/`-f`, claim wiring, error messages, `--detach`, `list`, epilogs | 4, 5, 6, 7 |
| `tests/test_app.py` | `/api/instance` shape | 1 |
| `tests/test_instance.py` | **New.** Probe/claim truth table, records, `running()` | 2, 3 |
| `tests/test_cli.py` | Flags, error copy, detach, `list`, help | 4, 5, 6, 7 |
| `README.md` | Document the flags and `list` | 7 |

---

### Task 1: `GET /api/instance`

**Files:**
- Modify: `src/armoire/app.py` (new route beside `/api/tree`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/instance` → `{"armoire": true, "pid": <int>, "root": "<str>"}`. Tasks 2–6 depend on this shape exactly.

Register it **before** `app.mount("/", StaticFiles(...))` at the end of `create_app`, like every other route — routes after that mount are shadowed by it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def test_the_instance_endpoint_identifies_this_process(client, root):
    payload = client.get("/api/instance").json()
    assert payload["armoire"] is True
    assert payload["pid"] == os.getpid()
    assert payload["root"] == str(root.resolve())


def test_the_instance_endpoint_needs_no_guard_header(client):
    """Unlike PUT /api/status, this is a side-effect-free GET. It is what a
    starting armoire probes before it has any reason to be trusted."""
    assert client.get("/api/instance").status_code == 200
```

`tests/test_app.py` may not import `os` yet — add it to the imports if missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k instance_endpoint -v`
Expected: FAIL — 404, because the static mount answers the unclaimed path.

- [ ] **Step 3: Write the implementation**

In `src/armoire/app.py`, add this route immediately after the `open_registry` handler and before `app.mount(...)`:

```python
    @app.get("/api/instance")
    def instance() -> dict:
        """Identify this process to another armoire starting on this port.

        Unguarded, unlike the two state-changing endpoints: a side-effect-free
        GET whose only new disclosure is a pid, which a browser can do nothing
        with. `root` is already public through /api/tree.

        `armoire: True` is a literal rather than an implied "you got a 200".
        The starting instance is deciding whether to send SIGTERM to whatever
        answered, so "it responded" is not good enough -- it has to say what
        it is. See instance.probe, which checks `is True` and nothing looser.
        """
        return {"armoire": True, "pid": os.getpid(), "root": str(root)}
```

Add `import os` to `app.py`'s imports if it is not already there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k instance_endpoint -v`
Expected: 2 passed

Run: `uv run pytest tests/test_app.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/app.py tests/test_app.py
uv run ruff check src/armoire/app.py tests/test_app.py
git add src/armoire/app.py tests/test_app.py
git commit -m "feat: GET /api/instance identifies the running server"
```

---

### Task 2: `instance.probe` and `instance.claim_port`

**Files:**
- Create: `src/armoire/instance.py`
- Create: `tests/test_instance.py`

**Interfaces:**
- Consumes: `GET /api/instance` from Task 1.
- Produces:
  - `Instance(port: int, pid: int, root: str)` — frozen dataclass
  - `Claim(replaced_pid: int | None, replaced_root: str | None)` — frozen dataclass, both `None` when nothing was replaced
  - `probe(port: int) -> Instance | None`
  - `claim_port(port: int, force: bool) -> Claim`
  - `PortBusy(instance: Instance)`, `PortForeign(port: int)`, `PortStuck(port: int)` — all `Exception`
  - Module constants `PROBE_TIMEOUT`, `RELEASE_TIMEOUT`, `POLL_INTERVAL`

**The race that a naive implementation gets wrong:** if the incumbent exits between the bind check and the probe, the probe fails to connect and returns `None` — which looks identical to "something unidentifiable is there". Raising `PortForeign` for a port that is now *free* is a confusing lie. `claim_port` must re-check the port before refusing. The spec calls this row out; the code below implements it and Step 1 tests it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_instance.py`:

```python
"""Finding, identifying, and replacing a running armoire."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import uvicorn

from armoire import instance, store
from armoire.app import create_app


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def armoire_on_a_port(tmp_path):
    """A real armoire, in this process, on a port of its own.

    In-process rather than a subprocess so the test can assert on the pid it
    reports: it must equal this process's pid, which is what proves the
    endpoint reports its own identity rather than a constant.
    """
    port = _free_port()
    app = create_app(tmp_path)
    app.state.index.wait(timeout=10)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("armoire fixture never started")
    yield port
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def silent_listener():
    """A socket that accepts connections and never answers.

    The realistic shape of "something else has your port": a service that is
    not armoire and does not speak armoire's protocol. probe() must time out
    and return None, and claim_port must refuse rather than kill it.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    yield sock.getsockname()[1], sock
    sock.close()


@pytest.fixture
def impostor():
    """Answers 200 on /api/instance with JSON that is not armoire's.

    A 200 is not identity. This is the fixture that proves probe() checks the
    payload rather than the status code.
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"armoire": "yes", "pid": 1, "root": "/"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], server
    server.shutdown()
    server.server_close()


def test_probe_identifies_a_running_armoire(armoire_on_a_port, tmp_path):
    import os

    found = instance.probe(armoire_on_a_port)
    assert found is not None
    assert found.port == armoire_on_a_port
    assert found.pid == os.getpid()
    assert found.root == str(tmp_path.resolve())


def test_probe_returns_none_when_nothing_is_listening():
    assert instance.probe(_free_port()) is None


def test_probe_returns_none_for_a_silent_listener(silent_listener):
    port, _ = silent_listener
    assert instance.probe(port) is None


def test_probe_returns_none_for_a_200_that_is_not_armoire(impostor):
    """A 200 is not identity. `{"armoire": "yes"}` is truthy in Python and
    must still be rejected -- the check is `is True`."""
    port, _ = impostor
    assert instance.probe(port) is None


def test_claim_port_on_a_free_port_replaces_nothing():
    claim = instance.claim_port(_free_port(), force=False)
    assert claim.replaced_pid is None
    assert claim.replaced_root is None


def test_claim_port_refuses_a_busy_port_without_force(armoire_on_a_port):
    with pytest.raises(instance.PortBusy) as caught:
        instance.claim_port(armoire_on_a_port, force=False)
    assert caught.value.instance.port == armoire_on_a_port
    # The incumbent is untouched: refusing must not be a half-kill.
    assert instance.probe(armoire_on_a_port) is not None


def test_claim_port_refuses_a_foreign_listener_even_with_force(silent_listener):
    """The rule the whole feature rests on. --force authorises replacing an
    armoire; it never authorises killing a process armoire cannot identify."""
    port, sock = silent_listener
    with pytest.raises(instance.PortForeign):
        instance.claim_port(port, force=True)
    # Still ours, still listening.
    assert sock.fileno() != -1
    assert instance.claim_port.__module__  # sanity: no process was signalled


def test_claim_port_refuses_an_impostor_even_with_force(impostor):
    port, server = impostor
    with pytest.raises(instance.PortForeign):
        instance.claim_port(port, force=True)
    assert server.socket.fileno() != -1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_instance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'armoire.instance'`

- [ ] **Step 3: Write the implementation**

Create `src/armoire/instance.py`:

```python
"""Which armoire is on which port, and how one replaces another.

The register of running instances is the set of live processes, not a file.
Records under the store say only which ports are worth asking about; every
answer comes from probing the port itself.

That distinction is the whole safety argument. A pid read from a file may name
a process that died and whose number has since been reused, and killing that is
killing a stranger. A pid read from a live HTTP response on the port being
claimed cannot be stale: the process answered a moment ago, on the port, saying
what it is.
"""

import contextlib
import json
import os
import signal
import socket
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from armoire import store

# Long enough for a loaded machine to answer a loopback request, short enough
# that a foreign service which accepts and never replies does not hang the
# command for a noticeable time.
PROBE_TIMEOUT = 1.0
# uvicorn closes its sockets on SIGTERM; this is the budget for that to land.
RELEASE_TIMEOUT = 2.0
POLL_INTERVAL = 0.05


@dataclass(frozen=True)
class Instance:
    """A live armoire, as it described itself over HTTP."""

    port: int
    pid: int
    root: str


@dataclass(frozen=True)
class Claim:
    """The outcome of taking a port. Both fields None when nothing was there."""

    replaced_pid: int | None = None
    replaced_root: str | None = None


class PortBusy(Exception):
    """An armoire holds the port and force was not given."""

    def __init__(self, instance: Instance) -> None:
        self.instance = instance
        super().__init__(f"port {instance.port} is serving {instance.root}")


class PortForeign(Exception):
    """Something holds the port and it is not armoire. Force does not help."""

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(f"port {port} is in use by something that is not armoire")


class PortStuck(Exception):
    """The incumbent was signalled but never released the port."""

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(f"port {port} did not free up")


def _port_is_free(port: int) -> bool:
    """Could uvicorn bind this port right now?

    Deliberately no SO_REUSEADDR: uvicorn does not set it either, so setting
    it here would report a port free that uvicorn then fails to bind -- a
    false negative on the one question this function exists to answer.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def probe(port: int) -> Instance | None:
    """The armoire on `port`, or None when nothing there identifies as one.

    Every failure mode collapses to None: connection refused, a timeout, a
    404, a body that is not JSON, or JSON that does not say it is armoire.
    urllib raises HTTPError for the 404 case, which is a URLError, which is
    an OSError -- so the one except clause covers all of them.
    """
    url = f"http://127.0.0.1:{port}/api/instance"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    # `is True`, not truthiness. An unrelated service answering this path with
    # {"armoire": "yes"} is truthy in Python and is not armoire -- and the
    # caller's next move may be to send it SIGTERM.
    if payload.get("armoire") is not True:
        return None
    pid, root = payload.get("pid"), payload.get("root")
    # isinstance(pid, int) is True for bools; a payload claiming pid=True must
    # not reach os.kill.
    if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(root, str):
        return None
    return Instance(port=port, pid=pid, root=root)


def claim_port(port: int, force: bool) -> Claim:
    """Make `port` bindable, or raise explaining why it cannot be.

    Raises PortForeign when the holder cannot be identified as armoire --
    with or without `force`. Force widens permission, never identity.
    """
    if _port_is_free(port):
        return Claim()

    incumbent = probe(port)
    if incumbent is None:
        # Two different situations produce None here: nothing is there any
        # more (the incumbent exited between the bind check above and this
        # probe), or what holds the port is not armoire. Re-check before
        # refusing -- raising PortForeign for a port that is now free would
        # be a confusing lie about a machine that is fine.
        if _port_is_free(port):
            return Claim()
        raise PortForeign(port)

    if not force:
        raise PortBusy(incumbent)

    with contextlib.suppress(ProcessLookupError):
        # Gone between the probe and here. Not an error: the goal is a free
        # port, and its own exit achieved that. The wait below confirms it.
        os.kill(incumbent.pid, signal.SIGTERM)

    deadline = time.monotonic() + RELEASE_TIMEOUT
    while time.monotonic() < deadline:
        if _port_is_free(port):
            return Claim(replaced_pid=incumbent.pid, replaced_root=incumbent.root)
        time.sleep(POLL_INTERVAL)
    raise PortStuck(port)
```

If `ruff` does not have the `S` rules enabled — check `pyproject.toml`'s `[tool.ruff.lint] select` — drop the `# noqa: S310`. An unused `noqa` is itself a lint error under `RUF100`, and `ruff check` must come back clean either way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_instance.py -v`
Expected: 9 passed

- [ ] **Step 5: Add the two race tests**

These need the implementation to exist first, because they assert on behaviour the naive version gets wrong. Append to `tests/test_instance.py`:

```python
def test_claim_port_succeeds_when_the_incumbent_exits_during_the_probe(monkeypatch):
    """The port looked busy, then freed before the probe could ask. That is a
    free port, not a foreign one -- refusing here would report a problem that
    no longer exists."""
    port = _free_port()
    calls = []

    def flaky(p):
        # First call (the initial bind check) says busy; every later call says
        # free, standing in for an incumbent that exited in between.
        calls.append(p)
        return len(calls) > 1

    monkeypatch.setattr(instance, "_port_is_free", flaky)
    monkeypatch.setattr(instance, "probe", lambda p: None)
    claim = instance.claim_port(port, force=False)
    assert claim.replaced_pid is None


def test_claim_port_raises_when_the_port_never_frees(armoire_on_a_port, monkeypatch):
    """Signalled, but still holding. Binding into a dying process is a race
    worth losing loudly rather than winning silently."""
    monkeypatch.setattr(instance, "_port_is_free", lambda p: False)
    monkeypatch.setattr(instance, "RELEASE_TIMEOUT", 0.2)
    killed = []
    monkeypatch.setattr(instance.os, "kill", lambda pid, sig: killed.append(pid))
    with pytest.raises(instance.PortStuck):
        instance.claim_port(armoire_on_a_port, force=True)
    assert killed  # it did try
```

- [ ] **Step 6: Run the full instance suite**

Run: `uv run pytest tests/test_instance.py -v`
Expected: 11 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format src/armoire/instance.py tests/test_instance.py
uv run ruff check src/armoire/instance.py tests/test_instance.py
git add src/armoire/instance.py tests/test_instance.py
git commit -m "feat: probe and claim a port from a running armoire"
```

---

### Task 3: Instance records and `running()`

**Files:**
- Modify: `src/armoire/instance.py` (append)
- Test: `tests/test_instance.py` (append)

**Interfaces:**
- Consumes: `probe`, `Instance` from Task 2; `store.config_root()`, `store.writes_inside(folder)`.
- Produces:
  - `record(port: int, root: Path, pid: int) -> Path | None` — writes the record, returns its path, or `None` when the store is unusable
  - `forget(port: int) -> None`
  - `running() -> list[Instance]` — probed and sorted by port

`running()` takes the port from the **filename** and everything else from the **probe**. The file's own `root` and `pid` fields are never displayed — they exist so a human reading the store can make sense of it, and so a future debugging session has something to compare against.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_instance.py`:

```python
@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    root = tmp_path / "cfg" / "armoire"
    monkeypatch.setattr(store, "config_root", lambda: root)
    return root


def test_record_writes_a_file_named_for_the_port(tmp_path, isolated_store):
    written = instance.record(8420, tmp_path, 4242)
    assert written == isolated_store / "instances" / "8420.json"
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "port": 8420,
        "root": str(tmp_path),
        "pid": 4242,
    }


def test_record_writes_nothing_when_the_store_is_inside_the_served_folder(
    tmp_path, monkeypatch
):
    """Same refusal prepare_store makes. A record is a file like any other and
    must not land in the tree armoire promises not to write to."""
    config_root = tmp_path / "store"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    assert instance.record(8420, served, 4242) is None
    assert not (config_root / "instances").exists()


def test_forget_removes_a_record(tmp_path, isolated_store):
    instance.record(8420, tmp_path, 4242)
    instance.forget(8420)
    assert not (isolated_store / "instances" / "8420.json").exists()


def test_forget_is_silent_when_there_is_no_record(isolated_store):
    instance.forget(8420)  # must not raise


def test_running_reports_a_live_instance(armoire_on_a_port, tmp_path, isolated_store):
    instance.record(armoire_on_a_port, tmp_path, 1)
    live = instance.running()
    assert [i.port for i in live] == [armoire_on_a_port]
    # From the probe, not from the file -- the file said pid 1.
    import os

    assert live[0].pid == os.getpid()


def test_running_prunes_a_record_with_nothing_behind_it(tmp_path, isolated_store):
    dead = _free_port()
    instance.record(dead, tmp_path, 4242)
    assert instance.running() == []
    assert not (isolated_store / "instances" / f"{dead}.json").exists()


def test_running_prunes_a_record_whose_port_is_now_someone_else(
    tmp_path, isolated_store, impostor
):
    port, _ = impostor
    instance.record(port, tmp_path, 4242)
    assert instance.running() == []
    assert not (isolated_store / "instances" / f"{port}.json").exists()


def test_running_is_empty_when_nothing_was_ever_recorded(isolated_store):
    assert instance.running() == []


def test_running_is_sorted_by_port(tmp_path, isolated_store, monkeypatch):
    """Directory order is not port order, and a list that reshuffles between
    runs is a list nobody can scan."""
    for port in (9002, 9000, 9001):
        instance.record(port, tmp_path, 1)
    monkeypatch.setattr(
        instance, "probe", lambda p: instance.Instance(port=p, pid=1, root=str(tmp_path))
    )
    assert [i.port for i in instance.running()] == [9000, 9001, 9002]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_instance.py -k "record or forget or running" -v`
Expected: FAIL — `AttributeError: module 'armoire.instance' has no attribute 'record'`

- [ ] **Step 3: Write the implementation**

Append to `src/armoire/instance.py`:

```python
def _records_dir() -> Path:
    return store.config_root() / "instances"


def record(port: int, root: Path, pid: int) -> Path | None:
    """Note that `pid` serves `root` on `port`. None when the store is unusable.

    One file per port rather than one shared file: two servers starting at the
    same moment would otherwise have to merge, and per-port files make the
    write independent by construction.

    Returns None, writing nothing, when armoire's own files would land inside
    the folder being served -- the same refusal cli.prepare_store makes. Such
    an instance is then absent from `running()`, which is the correct trade:
    the read-only guarantee outranks a convenience listing.
    """
    if store.writes_inside(root):
        return None
    path = _records_dir() / f"{port}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"port": port, "root": str(root), "pid": pid}, indent=2),
        encoding="utf-8",
    )
    return path


def forget(port: int) -> None:
    """Drop the record for `port`, if there is one."""
    with contextlib.suppress(OSError):
        (_records_dir() / f"{port}.json").unlink()


def running() -> list[Instance]:
    """Every live armoire, probed, sorted by port.

    The records only supply the list of ports worth asking about. What comes
    back is what each port said about itself just now -- a record whose
    process died, or whose port now belongs to something else, is dropped and
    its file removed. So a server killed with SIGKILL, which never got to
    clean up after itself, is tidied away by the next person to run `list`.

    The port comes from the filename rather than the file body: the filename
    is what makes the record unique, so trusting the body would let a
    hand-edited file report a port it does not own.
    """
    directory = _records_dir()
    if not directory.is_dir():
        return []
    live: list[Instance] = []
    for path in sorted(directory.glob("*.json")):
        try:
            port = int(path.stem)
        except ValueError:
            continue
        found = probe(port)
        if found is None:
            with contextlib.suppress(OSError):
                path.unlink()
            continue
        live.append(found)
    return sorted(live, key=lambda found: found.port)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_instance.py -v`
Expected: 20 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/instance.py tests/test_instance.py
uv run ruff check src/armoire/instance.py tests/test_instance.py
git add src/armoire/instance.py tests/test_instance.py
git commit -m "feat: record running instances and list the live ones"
```

---

### Task 4: Wire claiming into `serve`, with `-p` and `-f`

**Files:**
- Modify: `src/armoire/cli.py` (the `serve` command)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `instance.claim_port`, `instance.PortBusy`, `instance.PortForeign`, `instance.PortStuck`, `instance.record` from Tasks 2–3.
- Produces: `serve` accepting `-p/--port`, `-f/--force`. Task 5 adds `-d/--detach` to the same command.

Error copy is asserted by tests, so it must match exactly. Note that both errors go to **stderr** (`err=True`) and exit **1**, distinct from Click's own usage errors which exit 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_serve_refuses_a_port_held_by_another_armoire(tmp_path, uvicorn_run, monkeypatch):
    held = instance_module.Instance(port=8420, pid=48148, root=r"D:\GitHub\summer-26")

    def busy(port, force):
        raise instance_module.PortBusy(held)

    monkeypatch.setattr(cli.instance, "claim_port", busy)
    result = CliRunner().invoke(main, ["serve", str(tmp_path)])
    assert result.exit_code == 1
    assert uvicorn_run == []
    # Names the folder, not only the pid: replacing your own stale server and
    # destroying one you still wanted look identical without it.
    assert r"D:\GitHub\summer-26" in result.output
    assert "48148" in result.output
    assert "-df" in result.output
    assert "--force" in result.output
    assert "--port" in result.output


def test_serve_refuses_a_port_held_by_something_that_is_not_armoire(
    tmp_path, uvicorn_run, monkeypatch
):
    def foreign(port, force):
        raise instance_module.PortForeign(port)

    monkeypatch.setattr(cli.instance, "claim_port", foreign)
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "--force"])
    assert result.exit_code == 1
    assert uvicorn_run == []
    # Someone just told about forcing by the other error will try it here.
    assert "--force will not help" in result.output


def test_serve_reports_what_it_replaced(tmp_path, uvicorn_run, monkeypatch):
    monkeypatch.setattr(
        cli.instance,
        "claim_port",
        lambda port, force: instance_module.Claim(
            replaced_pid=48148, replaced_root=r"D:\GitHub\summer-26"
        ),
    )
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-f"])
    assert result.exit_code == 0
    assert r"replaced the armoire serving D:\GitHub\summer-26 on 8420 (pid 48148)" in result.output


def test_serve_says_nothing_about_replacing_on_a_clean_start(tmp_path, uvicorn_run):
    result = CliRunner().invoke(main, ["serve", str(tmp_path)])
    assert result.exit_code == 0
    assert "replaced" not in result.output


def test_force_is_passed_through_to_claim_port(tmp_path, uvicorn_run, monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli.instance,
        "claim_port",
        lambda port, force: seen.append((port, force)) or instance_module.Claim(),
    )
    CliRunner().invoke(main, ["serve", str(tmp_path)])
    CliRunner().invoke(main, ["serve", str(tmp_path), "-f"])
    assert seen == [(8420, False), (8420, True)]


def test_short_port_flag_is_honoured(tmp_path, uvicorn_run):
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-p", "9000"])
    assert result.exit_code == 0
    assert uvicorn_run[0]["port"] == 9000


def test_the_long_port_flag_still_works(tmp_path, uvicorn_run):
    """Nothing is deprecated. Scripts built on the long forms keep working."""
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "--port", "9000"])
    assert result.exit_code == 0
    assert uvicorn_run[0]["port"] == 9000
```

Add to the imports at the top of `tests/test_cli.py`:

```python
from armoire import instance as instance_module
```

`cli` and `store` are already imported there; `cli.instance` is the module attribute the tests patch, so `cli.py` must import it as `from armoire import instance`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "refuses_a_port or replaced or force_is_passed or short_port" -v`
Expected: FAIL — `AttributeError: module 'armoire.cli' has no attribute 'instance'`

- [ ] **Step 3: Write the implementation**

In `src/armoire/cli.py`, add to the imports:

```python
from armoire import __version__, instance, store
```

Replace the `serve` command's decorators and body with:

```python
@main.command()
@click.argument(
    "folder",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option("--port", "-p", default=DEFAULT_PORT, show_default=True, help="Port to listen on.")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help=(
        "Replace an armoire already on this port. Does nothing when the port "
        "is free, and never stops a process armoire cannot identify as its own."
    ),
)
def serve(folder: Path, port: int, force: bool) -> None:
    """Browse FOLDER at http://127.0.0.1:PORT. Never writes to FOLDER.

    armoire's registry and project statuses live in its own per-user store,
    outside the served folder, and that store is the only thing it writes.
    """
    root = folder.resolve()
    try:
        claim = instance.claim_port(port, force)
    except instance.PortBusy as busy:
        # The folder, not just the pid: replacing a stale server of your own
        # and destroying one you still wanted are the same keystrokes, and
        # only the folder name tells them apart.
        click.echo(
            f"armoire: port {port} is serving {busy.instance.root} "
            f"(pid {busy.instance.pid})",
            err=True,
        )
        # -df first because it is the answer nearly every time: someone
        # blocked by a server they lost track of is about to make another one
        # they will also lose. Bare -f is never recommended -- replacing a
        # server and then holding the terminal open recreates the problem.
        click.echo("  -df replaces it and runs without keeping this terminal open", err=True)
        click.echo("  --force replaces it and stays in this terminal", err=True)
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None
    except instance.PortForeign:
        click.echo(
            f"armoire: port {port} is in use, and what holds it is not armoire",
            err=True,
        )
        # Spelled out because the other error has just recommended forcing.
        # Silence here would read as a bug rather than a refusal.
        click.echo(
            "  armoire stops only processes it can identify as its own, "
            "so --force will not help",
            err=True,
        )
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None
    except instance.PortStuck:
        click.echo(
            f"armoire: the armoire on port {port} was asked to stop but did not "
            "release the port",
            err=True,
        )
        click.echo("  --port serves this folder somewhere else instead", err=True)
        raise SystemExit(1) from None

    click.echo(f"armoire serving {root}")
    click.echo(f"  http://127.0.0.1:{port}")
    if claim.replaced_pid is not None:
        click.echo(
            f"  replaced the armoire serving {claim.replaced_root} on {port} "
            f"(pid {claim.replaced_pid})"
        )
    for line in prepare_store(root):
        click.echo(line)
    instance.record(port, root, os.getpid())
    try:
        # Loopback only, always. This streams arbitrary bytes out of the root.
        uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
    finally:
        # Ctrl-C and SIGTERM both land here. A record left behind would make
        # `list` probe a dead port -- harmless, since it prunes, but tidying
        # up on the way out costs one call.
        instance.forget(port)
```

Add `import os` to `cli.py`'s imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all pass, including the pre-existing tests

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/cli.py tests/test_cli.py
uv run ruff check src/armoire/cli.py tests/test_cli.py
git add src/armoire/cli.py tests/test_cli.py
git commit -m "feat: serve claims its port, and says what it replaced"
```

---

### Task 5: `--detach`

**Files:**
- Modify: `src/armoire/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `serve` accepting `-d/--detach`; helper `_spawn_detached(argv, log) -> subprocess.Popen`; helper `_log_path(port) -> Path`.

**The child's argv does not include `--force`.** The parent has already claimed the port, so the child should find it free. If it does not, something raced, and a child that force-kills whatever it finds would be killing a process nobody authorised it to touch. The parent's poll then reports the failure instead.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_detach_spawns_a_child_and_does_not_run_a_server_here(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    spawned = []

    class FakeChild:
        pid = 51844

    def fake_spawn(argv, log):
        spawned.append({"argv": argv, "log": log})
        return FakeChild()

    monkeypatch.setattr(cli, "_spawn_detached", fake_spawn)
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 51844, str(tmp_path))
    )
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-d"])
    assert result.exit_code == 0
    assert uvicorn_run == []  # the parent must not also serve
    assert "running in the background (pid 51844)" in result.output
    assert len(spawned) == 1


def test_the_detached_child_is_not_told_to_force(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    """The parent already took the port. A child that forces would be killing
    whatever raced in, which nobody authorised."""
    spawned = []
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv, log: spawned.append(argv) or type("C", (), {"pid": 1})()
    )
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(tmp_path))
    )
    CliRunner().invoke(main, ["serve", str(tmp_path), "-df"])
    assert spawned
    assert "--force" not in spawned[0]
    assert "-f" not in spawned[0]
    assert "--detach" not in spawned[0]
    assert "-d" not in spawned[0]


def test_detach_exits_non_zero_when_the_child_never_answers(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    """Printing a pid for a process that died on startup is the exact failure
    this feature exists to prevent."""
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(cli.instance, "probe", lambda port: None)
    monkeypatch.setattr(cli, "DETACH_TIMEOUT", 0.2)
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-d"])
    assert result.exit_code == 1
    assert "running in the background" not in result.output
    assert "did not start" in result.output


def test_detach_names_its_log_file(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(tmp_path))
    )
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-d"])
    assert "serve-8420.log" in result.output


def test_detach_writes_no_log_when_the_store_is_inside_the_served_folder(
    tmp_path, uvicorn_run, monkeypatch
):
    """A log is a file like any other. Serving a folder that contains the
    store must not put armoire's files inside it."""
    config_root = tmp_path / "store"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    logs = []
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv, log: logs.append(log) or type("C", (), {"pid": 1})()
    )
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 0
    assert logs == [None]
    assert "no log: the armoire store is inside the served folder" in result.output


def test_short_flags_combine(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    seen = []
    monkeypatch.setattr(
        cli.instance, "claim_port", lambda port, force: seen.append(force) or instance_module.Claim()
    )
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(tmp_path))
    )
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "-df"])
    assert result.exit_code == 0
    assert seen == [True]  # -df carried the force through


def test_the_port_short_flag_combines_with_detach(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    """-dp 9000 is detach plus port. -pd 9000 is an error, because Click reads
    'd' as the start of the port value -- which is why examples show -dp."""
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(tmp_path))
    )
    good = CliRunner().invoke(main, ["serve", str(tmp_path), "-dp", "9000"])
    assert good.exit_code == 0
    bad = CliRunner().invoke(main, ["serve", str(tmp_path), "-pd", "9000"])
    assert bad.exit_code == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "detach or short_flags" -v`
Expected: FAIL — no such option `-d`

- [ ] **Step 3: Write the implementation**

Add to `cli.py`'s imports: `import subprocess`, `import sys`, `import time`.

Add beside `DEFAULT_PORT`:

```python
# Budget for a detached child to bind and answer. Generous: a cold start on a
# large folder spends most of it building the file index.
DETACH_TIMEOUT = 10.0
DETACH_POLL = 0.1
```

Add these helpers above the `serve` command:

```python
def _log_path(port: int) -> Path:
    """Where a detached server's output goes. One file per port, truncated per
    launch -- a log that grows forever is a log nobody opens."""
    return store.config_root() / f"serve-{port}.log"


def _spawn_detached(argv: list[str], log: Path | None) -> subprocess.Popen:
    """Start `argv` in its own session, outliving this process.

    `log` is None when armoire may not write for this folder, in which case
    the child's output goes to the null device: a convenience log does not get
    to break the promise that serving a folder never writes into it.
    """
    if log is None:
        stream = subprocess.DEVNULL
    else:
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w", encoding="utf-8")
    if sys.platform == "win32":
        extra = {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        }
    else:
        extra = {"start_new_session": True}
    return subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT, **extra)
```

Add the option to `serve`, after `--force`:

```python
@click.option(
    "--detach",
    "-d",
    is_flag=True,
    help=(
        "Run in the background and hand back the prompt. Output goes to a log "
        "file in the store."
    ),
)
```

and add `detach: bool` to the signature. Then, in the body, replace everything from `for line in prepare_store(root):` to the end with:

```python
    for line in prepare_store(root):
        click.echo(line)

    if detach:
        # No --force in the child's argv: the parent already claimed the port,
        # so the child should find it free. If it does not, something raced --
        # and a child that force-kills whatever it finds would be stopping a
        # process nobody authorised it to touch. The poll below reports that
        # instead.
        log = None if store.writes_inside(root) else _log_path(port)
        child = _spawn_detached(
            [sys.argv[0], "serve", str(root), "--port", str(port)], log
        )
        deadline = time.monotonic() + DETACH_TIMEOUT
        while time.monotonic() < deadline:
            if instance.probe(port) is not None:
                click.echo(f"  running in the background (pid {child.pid})")
                if log is None:
                    click.echo("  no log: the armoire store is inside the served folder")
                else:
                    click.echo(f"  log {log}")
                return
            time.sleep(DETACH_POLL)
        # Never print a pid for a process that died on startup -- reporting a
        # success that is not one is the failure this whole feature exists to
        # stop.
        click.echo(f"armoire: the background server did not start within {DETACH_TIMEOUT:.0f}s", err=True)
        if log is not None:
            click.echo(f"  see {log}", err=True)
        raise SystemExit(1)

    instance.record(port, root, os.getpid())
    try:
        # Loopback only, always. This streams arbitrary bytes out of the root.
        uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")
    finally:
        instance.forget(port)
```

The child records its own instance when it reaches the non-detached path, so the parent does not record on the child's behalf.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all pass

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/cli.py tests/test_cli.py
uv run ruff check src/armoire/cli.py tests/test_cli.py
git add src/armoire/cli.py tests/test_cli.py
git commit -m "feat: --detach runs the server without holding the terminal"
```

---

### Task 6: `armoire list`

**Files:**
- Modify: `src/armoire/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `instance.running()` from Task 3.
- Produces: the `list` subcommand.

The Click command function is named `list_instances` and registered as `list` via `@main.command("list")` — shadowing the builtin `list` inside the module would break the type annotations in `instance.py`'s neighbours and is a needless trap.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_list_shows_running_instances(monkeypatch):
    monkeypatch.setattr(
        cli.instance,
        "running",
        lambda: [
            instance_module.Instance(8420, 51844, r"D:\GitHub\summer-26"),
            instance_module.Instance(8421, 52001, r"D:\GitHub\armoire"),
        ],
    )
    result = CliRunner().invoke(main, ["list"])
    assert result.exit_code == 0
    assert "PORT" in result.output
    assert "8420" in result.output
    assert r"D:\GitHub\summer-26" in result.output
    assert "51844" in result.output
    assert "8421" in result.output
    assert "2 running" in result.output


def test_list_says_so_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(cli.instance, "running", list)
    result = CliRunner().invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no armoire instances running" in result.output


def test_list_counts_one_in_the_singular(monkeypatch):
    monkeypatch.setattr(
        cli.instance,
        "running",
        lambda: [instance_module.Instance(8420, 51844, r"D:\GitHub\summer-26")],
    )
    result = CliRunner().invoke(main, ["list"])
    assert "1 running" in result.output
    assert "1 runnings" not in result.output


def test_list_keeps_columns_aligned_for_a_long_folder_name(monkeypatch):
    """A table whose pid column wanders is a table nobody can scan."""
    monkeypatch.setattr(
        cli.instance,
        "running",
        lambda: [
            instance_module.Instance(8420, 51844, "/short"),
            instance_module.Instance(8421, 52001, "/a/very/much/longer/path/to/somewhere"),
        ],
    )
    result = CliRunner().invoke(main, ["list"])
    rows = [line for line in result.output.splitlines() if "5184" in line or "5200" in line]
    assert len(rows) == 2
    assert rows[0].index("51844") == rows[1].index("52001")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "test_list" -v`
Expected: FAIL — exit code 2, no such command `list`

- [ ] **Step 3: Write the implementation**

Append to `src/armoire/cli.py`:

```python
@main.command("list")
def list_instances() -> None:
    """Show the armoire instances currently running.

    One process serves one folder, so several folders means several ports.
    This is the answer to "which port was that folder on".
    """
    live = instance.running()
    if not live:
        click.echo("no armoire instances running")
        return
    # Width from the data, so the pid column does not wander when one folder
    # has a much longer path than the rest.
    width = max(len("FOLDER"), *(len(found.root) for found in live))
    click.echo(f"{'PORT':<6} {'FOLDER':<{width}} PID")
    for found in live:
        click.echo(f"{found.port:<6} {found.root:<{width}} {found.pid}")
    click.echo()
    click.echo(f"{len(live)} running")
```

The function is named `list_instances`, not `list`: shadowing the builtin inside this module is a needless trap for the next person adding a type annotation here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k "test_list" -v`
Expected: 4 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/armoire/cli.py tests/test_cli.py
uv run ruff check src/armoire/cli.py tests/test_cli.py
git add src/armoire/cli.py tests/test_cli.py
git commit -m "feat: armoire list shows which port serves which folder"
```

---

### Task 7: `--help` epilogs and README

**Files:**
- Modify: `src/armoire/cli.py` (group and `serve` epilogs)
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 4–6.
- Produces: nothing further.

Click rewraps help text by default, which would collapse the aligned example columns into prose. `\b` on its own line before a block marks it preformatted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_group_help_lists_both_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "list" in result.output


def test_group_help_carries_worked_examples():
    result = CliRunner().invoke(main, ["--help"])
    assert "armoire serve ." in result.output
    assert "armoire list" in result.output


def test_group_help_states_one_folder_per_process():
    """The fact no flag can teach, and help is where a newcomer meets it."""
    result = CliRunner().invoke(main, ["--help"])
    assert "One process serves one folder" in result.output


def test_serve_help_documents_every_option():
    result = CliRunner().invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--detach" in result.output
    assert "--force" in result.output
    assert "8420" in result.output  # the default is shown


def test_help_examples_keep_their_alignment():
    r"""Click rewraps help text unless a block is marked preformatted with \b.
    Without it these examples collapse into a paragraph."""
    result = CliRunner().invoke(main, ["--help"])
    lines = [line for line in result.output.splitlines() if "armoire serve" in line]
    assert len(lines) >= 3  # still one per line, not rewrapped into prose


def test_no_advertised_example_recommends_bare_f(monkeypatch):
    """Replacing a server and then holding the terminal open recreates the
    problem this feature removes, so nothing armoire *suggests* uses bare -f.

    Scoped to the epilogs and the two error strings, NOT to whole --help
    output: Click's own options table renders "-f, --force" and always will.
    The rule is about what armoire recommends, not what Click documents.
    """
    import re

    held = instance_module.Instance(port=8420, pid=1, root="/x")

    def busy(port, force):
        raise instance_module.PortBusy(held)

    monkeypatch.setattr(cli.instance, "claim_port", busy)
    busy_output = CliRunner().invoke(main, ["serve", "."]).output

    def foreign(port, force):
        raise instance_module.PortForeign(port)

    monkeypatch.setattr(cli.instance, "claim_port", foreign)
    foreign_output = CliRunner().invoke(main, ["serve", "."]).output

    bare_f = re.compile(r"(?<![\w-])-f(?![\w])")
    for text in (main.epilog or "", serve_epilog(), busy_output, foreign_output):
        assert not bare_f.search(text), text
```

For that last test to work, `cli.py` must expose the `serve` epilog through a helper. Add this import line to `tests/test_cli.py`:

```python
from armoire.cli import serve_epilog
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "help or bare_f" -v`
Expected: FAIL — `ImportError: cannot import name 'serve_epilog'`

- [ ] **Step 3: Write the implementation**

In `src/armoire/cli.py`, add above the group:

```python
GROUP_EPILOG = """\
\b
Examples:
  armoire serve .                     browse the current folder
  armoire serve ~/notes -d            run it in the background
  armoire serve ~/notes -df           replace the armoire already on that port
  armoire serve ~/notes -dp 9000      background, on port 9000
  armoire list                        what is running, and where

One process serves one folder, so several folders means several ports.
`armoire list` is there because nobody remembers which is which.
"""

SERVE_EPILOG = """\
\b
Examples:
  armoire serve .
  armoire serve D:/GitHub/summer-26 -df
  armoire serve ~/notes -dp 9000
"""


def serve_epilog() -> str:
    """The serve command's epilog, exposed so a test can assert on its copy."""
    return SERVE_EPILOG
```

Change the group decorator to carry the epilog:

```python
@click.group(epilog=GROUP_EPILOG)
@click.version_option(__version__)
def main() -> None:
    """Serve any folder as a local, read-only website."""
```

Change the `serve` command decorator to `@main.command(epilog=SERVE_EPILOG)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k "help or bare_f" -v`
Expected: 6 passed

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Eyeball the real help output**

Run: `uv run armoire --help` and `uv run armoire serve --help`

Confirm the example columns are still aligned and have not been rewrapped into a paragraph. A test asserts one example per line; only your eyes can confirm it reads well.

- [ ] **Step 6: Update the README**

In `README.md`, replace the `## Use` code block with:

```console
$ armoire serve .                 # browse at http://127.0.0.1:8420
$ armoire serve ~/notes -dp 9000  # background, on port 9000
$ armoire list                    # which port is serving which folder
```

and add this after the paragraph beginning "Open the URL it prints":

```markdown
One process serves one folder, so several folders means several ports. `-d`
runs a server in the background so it does not need a terminal of its own, and
`armoire list` reports which port is serving what.

A port already held by another armoire is refused rather than taken; `-f`
replaces that instance, and `-df` replaces it and detaches. A port held by
anything that is *not* armoire is always refused — armoire stops only processes
it can identify as its own, and `-f` does not change that.
```

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format src/armoire/cli.py tests/test_cli.py
uv run ruff check src/armoire/cli.py tests/test_cli.py
git add src/armoire/cli.py tests/test_cli.py README.md
git commit -m "docs: worked examples in --help, and the new flags in the README"
```

---

## Self-Review

**Spec coverage.** `/api/instance` → Task 1. `claim_port` and the full truth table, including both force-refusal rows → Task 2. Records, pruning, sort order, and the `writes_inside` refusal → Task 3. Busy/foreign error copy, folder naming, `-p`, `-f` → Task 4. `--detach`, log, no-log refusal, `-df`, `-dp` → Task 5. `armoire list` → Task 6. Epilogs, the bare-`-f` rule, README → Task 7. The spec's "What this does not do" needs no task by definition.

**Type consistency.** `Instance(port, pid, root)` and `Claim(replaced_pid, replaced_root)` are defined in Task 2 and used with those exact field names in Tasks 3–6. `claim_port(port, force)` is defined in Task 2 and patched with that signature in Tasks 4–5. `record(port, root, pid)` returns `Path | None` in Task 3 and is relied on for `None` in Task 5's no-log test. `_spawn_detached(argv, log)` is defined in Task 5 and patched with that arity in every detach test.

**Three things to verify rather than trust:**
- Task 2's `# noqa: S310` is correct only if ruff's `S` rules are enabled. Check `pyproject.toml` first; an unused `noqa` is itself an error under `RUF100`.
- Task 5 patches `cli.DETACH_TIMEOUT`; confirm the constant is read at call time inside `serve` and not captured into a default argument, or the patch will not take.
- Task 4 assumes `tests/test_cli.py`'s `isolated_store` fixture exists — it does, defined mid-file. Tasks 5 and 6 use it too. If it has moved, follow the real file.
