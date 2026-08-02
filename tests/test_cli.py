import pytest
from click.testing import CliRunner

from armoire import cli, store
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


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    return tmp_path / "cfg" / "armoire"


def test_first_serve_creates_a_registry_stub(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    assert store.registry_path(served).is_file()


def test_the_stub_parses_as_toml_and_declares_no_projects(tmp_path, isolated_store):
    from armoire.projects import load_registry

    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    registry = load_registry(served, store.registry_path(served))
    assert registry is not None
    assert registry.projects == []


def test_creating_the_stub_writes_nothing_into_the_served_folder(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    assert list(served.iterdir()) == []


def test_a_second_serve_does_not_overwrite_the_registry(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    cli.prepare_store(served)
    store.registry_path(served).write_text(
        '[[project]]\nname = "Mine"\npaths = ["."]\ncategory = "x"\n', encoding="utf-8"
    )
    cli.prepare_store(served)
    assert "Mine" in store.registry_path(served).read_text(encoding="utf-8")


def test_a_phase_two_registry_is_copied_into_the_store(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    (served / "armoire.toml").write_text(
        '[[project]]\nname = "Legacy"\npaths = ["."]\ncategory = "x"\n', encoding="utf-8"
    )
    cli.prepare_store(served)
    assert "Legacy" in store.registry_path(served).read_text(encoding="utf-8")


def test_migration_does_not_delete_the_original(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    legacy = served / "armoire.toml"
    legacy.write_text('[[project]]\nname = "Legacy"\npaths = ["."]\ncategory = "x"\n', "utf-8")
    cli.prepare_store(served)
    # Deleting it would itself be a write to the served folder.
    assert legacy.is_file()


def test_migration_reports_which_file_is_now_authoritative(tmp_path, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    (served / "armoire.toml").write_text(
        '[[project]]\nname = "L"\npaths = ["."]\ncategory = "x"\n', "utf-8"
    )
    lines = cli.prepare_store(served)
    joined = "\n".join(lines)
    assert str(store.registry_path(served)) in joined


def test_a_store_inside_the_served_folder_refuses_to_write(tmp_path, monkeypatch):
    served = tmp_path / "home"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: served / "cfg" / "armoire")
    lines = cli.prepare_store(served)
    assert not store.registry_path(served).exists()
    assert any("inside" in line for line in lines)


def test_the_refusal_leaves_the_served_folder_untouched(tmp_path, monkeypatch):
    served = tmp_path / "home"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: served / "cfg" / "armoire")
    cli.prepare_store(served)
    assert list(served.iterdir()) == []
