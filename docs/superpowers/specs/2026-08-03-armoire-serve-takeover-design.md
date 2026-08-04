# armoire serve takeover and detach — design

**Date:** 2026-08-03
**Status:** Approved.

## Problem

`armoire serve` holds the terminal until Ctrl-C. Close the window, forget which
window it was, and the server outlives your ability to find it. Starting a new
one then fails:

```
ERROR: [Errno 10048] error while attempting to bind on address
('127.0.0.1', 8420): only one usage of each socket address is normally permitted
```

The recovery is to hunt the process down by port and kill it, which is not
something a file viewer should ask of anyone.

The second half of the problem is why the old instance was invisible: there is
no way to run armoire without dedicating a terminal to it.

## Scope

**In:** `serve` replaces an armoire instance already holding the port; a
`--detach` flag that runs the server in the background; a log file so a
detached server's failures are recoverable.

**Out:** an `armoire stop` command (re-running `serve` is the restart); pidfiles;
`--port 0`; restart-on-crash supervision; any change to what armoire serves.

## Approach

Killing whatever holds a port is easy and wrong. The design question is how
armoire proves the process on port 8420 is armoire and not a database.

**A pidfile in the store.** Rejected. Verifying a recorded pid is still armoire
— rather than a recycled pid now belonging to something else — needs `psutil`
or platform-specific code. armoire has six runtime dependencies, all
load-bearing, and killing a recycled pid means killing an innocent process.

**A `POST /api/shutdown` endpoint.** Rejected. It avoids process-killing
entirely, and a local caller can already kill armoire through the OS, so it
grants no new capability. But a read-only file viewer should not ship a remote
kill switch to save one `os.kill`.

**An HTTP identity probe that returns the pid.** Chosen. Only armoire answers
armoire's endpoint, and it answers with its own pid. Identity is proven by the
response; the handle to kill comes from the live process itself, so a recycled
pid cannot be hit. No new dependency.

The rule the whole design rests on:

> armoire only ever kills a pid that armoire itself just reported, on the port
> armoire is about to take.

## The identity endpoint

`GET /api/instance` → `{"armoire": true, "pid": 51844, "root": "D:\\GitHub\\summer-26"}`

Unguarded, unlike `PUT /api/status` and `POST /api/registry/open`. It is a GET
with no side effect, and the only thing it newly exposes is a pid, which a
browser can do nothing with. `root` is already public through `/api/tree`.

`armoire` is a literal `true` rather than an implied "you got a 200": it makes
the check explicit at both ends, and a future unrelated service answering that
path with some other JSON does not read as armoire.

## Taking the port

One helper, `ensure_port_free(port) -> int | None`, returning the pid it
replaced or `None` when nothing needed replacing. It runs in the process the
user invoked — not in the detached child — so the parent can report what it did.

1. Try to bind a probe socket to `127.0.0.1:<port>`. Binds cleanly → close it,
   return `None`. Nothing is there.
2. Bind fails → `GET http://127.0.0.1:<port>/api/instance`, 1s timeout.
   - **Answers with `armoire: true` and a pid** → `os.kill(pid, SIGTERM)`, then
     poll until the port accepts a bind, up to 2s. Return the pid.
   - **Port frees before the kill lands** (the incumbent exited on its own
     between the failed bind and the probe) → return `None`.
   - **Anything else** — connection refused, a timeout, a 404, JSON without
     `armoire: true` → **kill nothing.** Raise, and let the CLI exit non-zero
     naming what happened.
   - **Killed, but the port never frees inside the budget** → raise. Do not
     bind-race a dying process.

The incumbent's served folder is not consulted. A port holds one server, and
`serve --port 8420` means "be the armoire on 8420" — replacing an instance that
was serving a different folder is the intended behaviour, not an edge case. The
replacement line names the pid so the swap is never silent.

`SIGTERM` rather than `SIGKILL`: uvicorn installs a handler for it and shuts
down its own sockets. On Windows `os.kill` maps `SIGTERM` to
`TerminateProcess`, which is abrupt but correct here — armoire holds no
write transaction that an abrupt end could tear, because `serve` never writes
to the served folder and `write_state` is atomic.

## Detaching

`--detach` re-launches `sys.argv` minus the flag through `subprocess.Popen`:

- **Windows** — `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
- **POSIX** — `start_new_session=True`

The parent then polls `/api/instance` until the child answers, up to 10s, and
only then prints `running in the background (pid N)`. Printing before the child
has bound would report success for a process that died on startup — the exact
failure this feature exists to prevent. If the child never answers, the parent
says so, points at the log, and exits non-zero.

Takeover happens in the parent, before the spawn, so the child never races the
process it is replacing.

## Output

Foreground, having replaced an instance:

```
armoire serving D:\GitHub\summer-26
  http://127.0.0.1:8420
  replaced the armoire already on 8420 (pid 48148)
  tip: --detach keeps it running without this terminal
  registry C:\Users\dafuz\AppData\Roaming\armoire\folders\summer-26-74c70453\registry.toml
```

The tip appears **only** when a takeover actually happened **and** `--detach`
was not passed. That pairing is the whole point: someone replacing an instance
they had lost track of, about to create another one they will also lose. It is
not printed on a clean start — there is nothing to infer from a first launch —
and not in detached mode, where the advice is already taken.

Detached:

```
armoire serving D:\GitHub\summer-26
  http://127.0.0.1:8420
  replaced the armoire already on 8420 (pid 48148)
  running in the background (pid 51844)
  log C:\Users\dafuz\AppData\Roaming\armoire\serve-8420.log
  registry C:\Users\dafuz\AppData\Roaming\armoire\folders\summer-26-74c70453\registry.toml
```

Port held by something else, exit code 1:

```
armoire: port 8420 is in use, and what holds it is not armoire
  armoire stops only processes it can identify as its own
  use --port to pick another, or stop that process yourself
```

No `--detach` tip here. Detaching would not free that port, so the hint would
send the reader the wrong way.

## Logs

A detached server with nowhere to write is a server whose crash you never see.
`--detach` redirects the child's stdout and stderr to
`<store>/serve-<port>.log`, truncated per launch, and prints the path. The file
sits beside `folders/` in the store root, not inside any folder's directory:
it belongs to a port, and across launches that port may serve different folders.

**Except when the store is inside the served folder.** `store.writes_inside`
already catches that case, and `prepare_store` refuses to write anything —
serving a home directory, or `%APPDATA%` itself, must not put armoire's files
in the tree it is serving. A log is a file like any other, so `--detach`
inherits that refusal: when `writes_inside(folder)` is true it opens no log,
discards the child's output to the null device, and says so:

```
  running in the background (pid 51844)
  no log: the armoire store is inside the served folder
```

Detaching still works; only the log is withheld. Writing it would break the one
guarantee armoire makes, and `test_serving_never_writes_to_disk` exists to
catch precisely this.

Foreground mode writes no log — the terminal is the log.

## Testing

- `/api/instance` returns `armoire: true`, `os.getpid()`, and the served root.
- `ensure_port_free` on a free port: returns `None`, kills nothing.
- `ensure_port_free` against a real armoire on the port: returns that pid, the
  process is gone, the port binds.
- **`ensure_port_free` against a non-armoire listener: raises, and the listener
  is still alive afterwards.** The single most important test here — it is what
  separates this feature from a footgun.
- `ensure_port_free` against a listener that answers 200 with JSON lacking
  `armoire: true`: raises, listener survives. A 200 is not identity.
- The tip appears on takeover without `--detach`; absent on a clean start;
  absent with `--detach`; absent on the non-armoire error path.
- `--detach` returns promptly, the child answers `/api/instance`, the log file
  exists. A child that cannot start makes the parent exit non-zero rather than
  print a pid.
- `--detach` with the store inside the served folder: the child still starts,
  no log file is created anywhere under the served folder, and the output says
  why. `test_serving_never_writes_to_disk` covers the served tree; this test
  covers the launch path that would otherwise sidestep it.
- Every test that kills something kills only a process the test itself started.

## What this does not do

No supervision: a detached server that crashes at 3am stays down. Restarting it
is `serve` again, which is now also how you replace it. Adding a supervisor
means a supervisor to install, monitor, and stop — a service, where this is a
tool you point at a folder.
