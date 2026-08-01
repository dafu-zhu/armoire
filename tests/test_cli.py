import pytest
from click.testing import CliRunner

from armoire.cli import main


@pytest.fixture(autouse=True)
def uvicorn_run(monkeypatch):
    """Capture uvicorn.run instead of starting a real server.

    autouse so a regression in argument validation fails fast: without it, a
    test whose validation stops working reaches the real blocking call and
    hangs the suite until CI times out.
    """
    calls = []

    def fake_run(app, host, port, log_level):
        calls.append({"app": app, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr("armoire.cli.uvicorn.run", fake_run)
    return calls


def test_serve_rejects_a_missing_folder(tmp_path, uvicorn_run):
    result = CliRunner().invoke(main, ["serve", str(tmp_path / "nope")])
    assert result.exit_code == 2  # click UsageError, not a crash (which is 1)
    assert uvicorn_run == []


def test_serve_rejects_a_file(tmp_path, uvicorn_run):
    target = tmp_path / "a.txt"
    target.write_text("x")
    result = CliRunner().invoke(main, ["serve", str(target)])
    assert result.exit_code == 2
    assert uvicorn_run == []


def test_serve_binds_loopback_only(tmp_path, uvicorn_run):
    result = CliRunner().invoke(main, ["serve", str(tmp_path)])
    assert result.exit_code == 0
    assert len(uvicorn_run) == 1
    assert uvicorn_run[0]["host"] == "127.0.0.1"
    assert uvicorn_run[0]["port"] == 8420


def test_port_flag_is_honoured(tmp_path, uvicorn_run):
    result = CliRunner().invoke(main, ["serve", str(tmp_path), "--port", "9000"])
    assert result.exit_code == 0
    assert uvicorn_run[0]["port"] == 9000
