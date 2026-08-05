import pytest
from click.testing import CliRunner

from armoire import cli, store
from armoire import instance as instance_module
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
    # The path alone proves nothing about migration: the "no registry yet -
    # created ..." branch names the same file, so this test passed unchanged
    # against a prepare_store that ignored the legacy file entirely and wrote
    # a stub over it. What the name claims is that the output says a migration
    # happened, names the file left behind, and says which of the two now
    # wins.
    assert "migrated" in joined, joined
    assert str(served / "armoire.toml") in joined, joined
    assert "authoritative" in joined, joined
    assert "ignored" in joined, joined


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


def test_a_folder_inside_the_stores_own_tree_refuses_to_write(tmp_path, monkeypatch):
    """The weaker question -- does config_root() sit inside the served folder
    -- is true only when the served folder is an *ancestor* of the store.
    Serving config_root()'s own "folders" directory is the opposite relation
    (the served folder is a *descendant* of the store), and that question
    answers False there: config_root() is not inside a folder that is itself
    inside config_root(). prepare_store must still refuse, because
    registry_path(served) -- folder_dir(served)/"registry.toml", keyed off
    served's own hash -- lands inside `served` regardless of which direction
    the ancestry runs."""
    config_root = tmp_path / "cfg" / "armoire"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    lines = cli.prepare_store(served)
    assert not store.registry_path(served).exists()
    assert list(served.rglob("*")) == []
    assert any("inside" in line for line in lines)


def test_serve_creates_the_registry_in_the_store(tmp_path, uvicorn_run):
    CliRunner().invoke(main, ["serve", str(tmp_path)])
    assert store.registry_path(tmp_path).is_file()


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
