# armoire serve takeover, detach, and list — design

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

Two further problems sit behind that one. There is no way to run armoire
without dedicating a terminal to it. And because one process serves exactly one
folder, several folders means several ports — with nothing anywhere recording
which port is which.

## Scope

**In:** `--force` to replace an armoire already holding the port; `--detach` to
run in the background; `armoire list` to show what is running where; short
flags `-p`, `-d`, and `-f` (with `-df` the advertised pairing); worked examples
in `--help` at both the group and `serve` level. Every existing long form keeps
working unchanged.

**Out:** `armoire stop`; per-folder port memory (`list` answers the question
without adding hidden state); serving several folders from one process;
restart-on-crash supervision; any change to what armoire serves.

## Approach

Killing whatever holds a port is easy and wrong. The design question is how
armoire proves the process on port 8420 is armoire and not a database.

**A pidfile as the source of truth.** Rejected. Verifying a recorded pid is
still armoire — rather than a recycled pid now belonging to something else —
needs `psutil` or platform-specific code. armoire has six runtime dependencies,
all load-bearing, and killing a recycled pid means killing an innocent process.

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

`--force` widens *permission*, never *identity*. It authorises replacing an
armoire. It never authorises killing a process armoire could not identify.

## The identity endpoint

`GET /api/instance` → `{"armoire": true, "pid": 51844, "root": "D:\\GitHub\\summer-26"}`

Unguarded, unlike `PUT /api/status` and `POST /api/registry/open`. It is a GET
with no side effect, and the only thing it newly exposes is a pid, which a
browser can do nothing with. `root` is already public through `/api/tree`.

`armoire` is a literal `true` rather than an implied "you got a 200": it makes
the check explicit at both ends, and an unrelated service answering that path
with some other JSON does not read as armoire.

## Claiming the port

One helper, `claim_port(port, force) -> Claim`, run in the process the user
invoked — not in the detached child — so the parent reports what it did.
`Claim` carries `replaced_pid` and `replaced_root`, both `None` when nothing
was replaced.

1. Try to bind a probe socket to `127.0.0.1:<port>`. Binds cleanly → close it,
   return an empty `Claim`. Nothing is there.
2. Bind fails → `GET http://127.0.0.1:<port>/api/instance`, 1s timeout.

| Probe result | `--force` absent | `--force` present |
|---|---|---|
| Answers `armoire: true` with a pid | `PortBusy(root, pid)` — refuse | `SIGTERM`, wait for the port, return the pid and root |
| Refused, timed out, 404, or JSON without `armoire: true` | `PortForeign` — refuse | `PortForeign` — **still refuse** |
| Port freed between the failed bind and the probe | proceed, empty `Claim` | proceed, empty `Claim` |
| Killed, but the port never frees within 2s | `PortStuck` — refuse | `PortStuck` — refuse |

The second row is the one that matters: `--force` does not escalate to killing
an unidentified process. A user who wants that has `--port`, or their own
task manager.

The incumbent's served folder is not consulted for the decision. A port holds
one server, and `serve --port 8420 --force` means "be the armoire on 8420".
Replacing an instance serving a different folder is intended, not an edge case
— which is exactly why the folder is named in both the refusal and the
replacement line. The default port is 8420, so `armoire serve OTHER -df` with
no `--port` is a plausible slip, and the output has to make it legible.

`SIGTERM` rather than `SIGKILL`: uvicorn installs a handler and shuts down its
own sockets. On Windows `os.kill` maps `SIGTERM` to `TerminateProcess`, which
is abrupt but correct here — `serve` never writes to the served folder, and
`write_state` is atomic, so an abrupt end tears nothing.

## Detaching

`--detach` re-launches the CLI as `sys.executable -m armoire.cli` through
`subprocess.Popen`, avoiding Windows console-script shims:

- **Windows** — `creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`,
  with hidden `STARTUPINFO`
- **POSIX** — `start_new_session=True`

The parent polls `/api/instance` until the child answers, up to 10s, and only
then prints `running in the background (pid N)`. Printing before the child has
bound would report success for a process that died on startup — the exact
failure this feature exists to prevent. If the child never answers, the parent
says so, points at the log, and exits non-zero.

The port is claimed in the parent, before the spawn, so the child never races
the process it replaced.

## Flags

```
armoire serve FOLDER [-p/--port N] [-d/--detach] [-f/--force]
armoire list
```

**Nothing is deprecated.** `--port`, `--detach`, and `--force` all remain
first-class spellings; the short forms are additions, not replacements. Scripts
and muscle memory built on the long forms keep working, and the long forms are
what the error messages use, since an error read once should not be a puzzle.

`-d` and `-f` are Click boolean flags, so `-df` combines them without extra
work. `-p` takes a value, so when combined it goes last and the value follows:
`-dp 9000` is `--detach --port 9000`. `-pd 9000` is an error — Click would read
`d` as the start of the port value — which is reason enough for the examples to
show `-dp` and never `-pd`.

**Bare `-f` is never advertised.** Replacing a server and then keeping the
terminal open reproduces the problem this feature exists to remove, so no help
text or error message ever recommends `-f` on its own — they offer `-df` and
the long `--force`. The short flag still exists, because `-df` decomposes into
`-d -f` and cannot parse without it.

`--force` on its own remains fully supported, not deprecated: replacing a
misbehaving server and watching the replacement in the foreground is a real
thing to want. It is simply not a thing armoire suggests.

## `--help`

Click generates help from docstrings and option declarations, so today
`armoire --help` lists the commands and nothing else — no worked invocation
anywhere. Someone who cannot remember whether it is `--port` or `-p`, or which
folder is on which port, gets no answer from the tool itself.

Both levels gain an `epilog` of real commands.

**`armoire --help`**

```
Usage: armoire [OPTIONS] COMMAND [ARGS]...

  Serve any folder as a local, read-only website.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  list   Show the armoire instances currently running.
  serve  Browse FOLDER at http://127.0.0.1:PORT.

Examples:
  armoire serve .                     browse the current folder
  armoire serve ~/notes -d            run it in the background
  armoire serve ~/notes -df           replace the armoire already on that port
  armoire serve ~/notes -dp 9000      background, on port 9000
  armoire list                        what is running, and where

One process serves one folder, so several folders means several ports.
`armoire list` is there because nobody remembers which is which.
```

**`armoire serve --help`**

```
Usage: armoire serve [OPTIONS] FOLDER

  Browse FOLDER at http://127.0.0.1:PORT. Never writes to FOLDER.

  armoire's registry and project statuses live in its own per-user store,
  outside the served folder, and that store is the only thing it writes.

Options:
  -p, --port INTEGER  Port to listen on.  [default: 8420]
  -d, --detach        Run in the background and hand back the prompt. Output
                      goes to a log file in the store.
  -f, --force         Replace an armoire already on this port. Does nothing
                      when the port is free, and never stops a process armoire
                      cannot identify as its own.
  --help              Show this message and exit.

Examples:
  armoire serve .
  armoire serve D:/GitHub/summer-26 -df
  armoire serve ~/notes -dp 9000
```

The last line of the group epilog carries the fact that no flag can teach:
armoire is one-folder-per-process. That is the thing a newcomer gets wrong, and
help output is where they will meet it.

Click rewraps epilog text by default, which would collapse the aligned example
columns into prose. The epilogs use `\b` escapes to mark those blocks as
preformatted.

## Output

**Port busy, no `--force`** — exit 1:

```
armoire: port 8420 is serving D:\GitHub\summer-26 (pid 48148)
  -df replaces it and runs without keeping this terminal open
  --force replaces it and stays in this terminal
  --port serves this folder somewhere else instead
```

`-df` is listed first because it is the answer nearly every time: someone
blocked by a server they had lost track of is about to create another one they
will also lose.

Naming the folder is what makes a mistake read as a mistake: replacing your own
stale server and destroying a server you still wanted look identical without it.
The `-df` line is where the detach hint belongs — the moment you are blocked by
a server you had lost track of is the moment to learn you need not lose the
next one.

**Replaced, foreground:**

```
armoire serving D:\GitHub\armoire
  http://127.0.0.1:8420
  replaced the armoire serving D:\GitHub\summer-26 on 8420 (pid 48148)
  registry C:\Users\dafuz\AppData\Roaming\armoire\folders\armoire-6c554005\registry.toml
```

**Replaced, detached:**

```
armoire serving D:\GitHub\armoire
  http://127.0.0.1:8420
  replaced the armoire serving D:\GitHub\summer-26 on 8420 (pid 48148)
  running in the background (pid 51844)
  log C:\Users\dafuz\AppData\Roaming\armoire\serve-8420.log
  registry C:\Users\dafuz\AppData\Roaming\armoire\folders\armoire-6c554005\registry.toml
```

**Port held by something that is not armoire** — exit 1, with or without
`--force`:

```
armoire: port 8420 is in use, and what holds it is not armoire
  armoire stops only processes it can identify as its own, so --force will not help
  --port serves this folder somewhere else instead
```

Saying `--force will not help` explicitly is deliberate. A user who has just
been told about forcing by the other error will try it here, and silence would
read as a bug rather than a refusal.

## `armoire list`

```
$ armoire list
PORT   FOLDER                       PID
8420   D:\GitHub\summer-26          51844
8421   D:\GitHub\armoire            52001

2 running
```

Empty case: `no armoire instances running`.

**How it knows.** `serve` writes `<store>/instances/<port>.json` at startup:
`{"port": 8420, "root": "...", "pid": 51844}`. One file per port, not one
shared file — two servers starting at once would otherwise need a merge, and
per-port files make the write independent by construction.

**The file is a hint, never the truth.** `list` reads the directory to learn
which ports are worth asking about, then probes `/api/instance` on each. What
it prints comes from the probe. A port that does not answer, or answers as
something else, is dropped from the output and its file removed — so a
kill -9'd server cleans itself up the next time anyone runs `list`. This is the
same discipline as the takeover path: files suggest, live processes decide.

**Ordering** is by port, ascending — stable across runs, unlike directory order.

## When the store is unwritable

`store.writes_inside` already catches the case where armoire's own files would
land inside the folder being served — serving a home directory, or `%APPDATA%`
itself — and `prepare_store` refuses to write anything there.

The log and the instance file are files like any other, so both inherit that
refusal. `--detach` still works; it discards the child's output to the null
device and says why:

```
  running in the background (pid 51844)
  no log: the armoire store is inside the served folder
```

Such an instance does not appear in `armoire list`, because nothing recorded
it. That is the correct trade: `test_serving_never_writes_to_disk` exists to
guarantee armoire does not write into the tree it serves, and a convenience
feature does not get to punch a hole in it.

Foreground mode writes no log — the terminal is the log.

## Testing

**Identity**
- `/api/instance` returns `armoire: true`, `os.getpid()`, and the served root.

**Claiming**
- Free port: empty `Claim`, nothing killed.
- Real armoire on the port, `force=True`: returns that pid and root, the process
  is gone, the port binds.
- Real armoire on the port, `force=False`: raises `PortBusy` carrying the root
  and pid, **and the incumbent is still alive afterwards**.
- **Non-armoire listener, `force=True`: raises `PortForeign`, and the listener
  is still alive afterwards.** The single most important test here — it is what
  separates this feature from a footgun.
- Listener answering 200 with JSON lacking `armoire: true`, `force=True`:
  raises `PortForeign`, listener survives. A 200 is not identity.

**CLI**
- The busy error names the folder, the pid, `-df`, and `--force`; exit 1.
- The foreign error says `--force will not help`; exit 1.
- `-df` parses as both flags; `-d` and `--force` each parse alone.
- `-p 9000` and `--port 9000` are equivalent; `-dp 9000` parses as detach plus
  port. Every long form still works on its own — nothing was replaced.
- Replacement line names the replaced folder, not only its pid.
- **No example or error message recommends bare `-f`.** Scope the assertion to
  the two epilogs and the two error strings — *not* to whole `--help` output,
  because Click's own options table renders `-f, --force` and always will. The
  rule is about what armoire suggests, not what Click documents. This is the
  rule most likely to erode as those strings get edited, so it gets a test.

**Help**
- `armoire --help` exits 0 and names both `serve` and `list`.
- The group epilog states one-folder-per-process.
- `armoire serve --help` documents `--port`, `-d`, and `-f`, and shows the
  default port.
- Example blocks keep their column alignment — the `\b` escapes work, and
  Click has not rewrapped them into prose.

**Detach**
- Returns promptly, child answers `/api/instance`, log file exists.
- A child that cannot start makes the parent exit non-zero rather than print a
  pid.
- Store inside the served folder: child starts, no file is created anywhere
  under the served folder, output says why.

**list**
- Two live instances: both listed, ordered by port.
- A recorded port with nothing behind it: omitted, and its file removed.
- A recorded port answering as something else: omitted, file removed.
- No instances: `no armoire instances running`.

Every test that kills something kills only a process the test itself started.

## What this does not do

No supervision: a detached server that crashes at 3am stays down. Restarting it
is `serve` again. Adding a supervisor means a supervisor to install, monitor,
and stop — a service, where this is a tool you point at a folder.

No per-folder port memory. `list` answers "which port was that folder on"
without armoire silently choosing ports on your behalf, and a remembered port
that quietly changes when it is taken is harder to reason about than a port you
typed.
