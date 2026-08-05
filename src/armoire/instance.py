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
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:
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
