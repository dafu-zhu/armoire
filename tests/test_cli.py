import subprocess
import sys

import pytest
from click.testing import CliRunner

from armoire import cli, store
from armoire import instance as instance_module
from armoire.cli import main, serve_epilog


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


def test_detach_spawns_a_child_and_returns(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    spawned = []
    monkeypatch.setattr(
        cli,
        "_spawn_detached",
        lambda argv, log: spawned.append((argv, log)) or type("C", (), {"pid": 48148})(),
    )
    monkeypatch.setattr(
        cli.instance,
        "probe",
        lambda port: instance_module.Instance(port, 48148, str(served)),
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 0
    assert uvicorn_run == []
    assert "running in the background" in result.output
    assert "48148" in result.output
    assert len(spawned) == 1


def test_the_detached_child_is_not_told_to_force(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    """The parent already took the port. A child that forces would be killing
    whatever raced in, which nobody authorised."""
    served = tmp_path / "served"
    served.mkdir()
    spawned = []
    monkeypatch.setattr(
        cli,
        "_spawn_detached",
        lambda argv, log: spawned.append(argv) or type("C", (), {"pid": 1})(),
    )
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    CliRunner().invoke(main, ["serve", str(served), "-df"])
    assert spawned
    assert "--force" not in spawned[0]
    assert "-f" not in spawned[0]
    assert "--detach" not in spawned[0]
    assert "-d" not in spawned[0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process creation flags")
def test_windows_detach_requests_no_visible_console(monkeypatch):
    captured = {}

    def fake_popen(argv, stdout, stderr, **extra):
        captured.update({"argv": argv, "stdout": stdout, "stderr": stderr, **extra})
        return type("C", (), {"pid": 1})()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.sys, "platform", "win32")

    cli._spawn_detached(["python", "-m", "armoire.cli"], None)

    assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not captured["creationflags"] & subprocess.DETACHED_PROCESS
    startupinfo = captured["startupinfo"]
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


def test_detach_relaunches_the_python_module_not_the_console_shim(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    """The detached process must be the Python server process itself.

    Relaunching sys.argv[0] works in tests, but installed Windows console
    shims can keep the real Python child tied to the terminal lifetime.
    """
    served = tmp_path / "served"
    served.mkdir()
    spawned = []
    monkeypatch.setattr(
        cli,
        "_spawn_detached",
        lambda argv, log: spawned.append(argv) or type("C", (), {"pid": 1})(),
    )
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 0
    assert spawned
    assert spawned[0][:3] == [sys.executable, "-m", "armoire.cli"]
    assert spawned[0][3:] == ["serve", str(served.resolve()), "--port", "8420"]


def test_detach_exits_non_zero_when_the_child_never_answers(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    """Printing a pid for a process that died on startup is the exact failure
    this feature exists to prevent."""
    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(cli.instance, "probe", lambda port: None)
    monkeypatch.setattr(cli, "DETACH_TIMEOUT", 0.2)
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 1
    assert "running in the background" not in result.output
    assert "did not start" in result.output


def test_detach_names_its_log_file(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert "serve-8420.log" in result.output


def test_detach_reports_the_server_pid_not_the_launcher_pid(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 111})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 222, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 0
    assert "pid 222" in result.output
    assert "pid 111" not in result.output


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
        cli,
        "_spawn_detached",
        lambda argv, log: logs.append(log) or type("C", (), {"pid": 1})(),
    )
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-d"])
    assert result.exit_code == 0
    assert logs == [None]
    assert "no log: the armoire store is inside the served folder" in result.output


def test_short_flags_combine(tmp_path, uvicorn_run, monkeypatch, isolated_store):
    served = tmp_path / "served"
    served.mkdir()
    seen = []
    monkeypatch.setattr(
        cli.instance,
        "claim_port",
        lambda port, force: seen.append(force) or instance_module.Claim(),
    )
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    result = CliRunner().invoke(main, ["serve", str(served), "-df"])
    assert result.exit_code == 0
    assert seen == [True]  # -df carried the force through


def test_the_port_short_flag_combines_with_detach(
    tmp_path, uvicorn_run, monkeypatch, isolated_store
):
    """-dp 9000 is detach plus port. -pd 9000 is an error, because Click reads
    'd' as the start of the port value -- which is why examples show -dp."""
    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv, log: type("C", (), {"pid": 1})())
    monkeypatch.setattr(
        cli.instance, "probe", lambda port: instance_module.Instance(port, 1, str(served))
    )
    good = CliRunner().invoke(main, ["serve", str(served), "-dp", "9000"])
    assert good.exit_code == 0
    bad = CliRunner().invoke(main, ["serve", str(served), "-pd", "9000"])
    assert bad.exit_code == 2


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


def test_group_help_lists_both_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "list" in result.output


def test_cli_module_is_executable():
    result = subprocess.run(
        [sys.executable, "-m", "armoire.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "version" in result.stdout


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
