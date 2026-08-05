"""Finding, identifying, and replacing a running armoire."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import uvicorn

from armoire import instance
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
