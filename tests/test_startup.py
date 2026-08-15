from pathlib import Path

from click.testing import CliRunner

from armoire import instance, startup, store
from armoire.cli import main


def test_remove_deletes_task_and_stops_matching_server_without_touching_folder_or_registry(
    tmp_path, monkeypatch
):
    config_root = tmp_path / "cfg" / "armoire"
    appdata = tmp_path / "roaming"
    system_root = tmp_path / "windows"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("SystemRoot", str(system_root))
    served = tmp_path / "summer-26"
    served.mkdir()
    content = served / "README.md"
    content.write_text("notes", encoding="utf-8")
    registry = store.registry_path(served)
    registry.parent.mkdir(parents=True)
    registry.write_text("[[project]]\n", encoding="utf-8")
    (config_root / "servers.csv").parent.mkdir(parents=True, exist_ok=True)
    (config_root / "servers.csv").write_text(
        f"Name,Folder,Port\nsummer-26,{served.resolve()},8420\n", encoding="utf-8"
    )
    script = config_root / "startup" / "summer-26.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("armoire serve ...", encoding="utf-8")
    launcher = (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "armoire summer-26.cmd"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("powershell ...", encoding="utf-8")
    task = system_root / "System32" / "Tasks" / "armoire summer-26"
    task.parent.mkdir(parents=True)
    task.write_text("scheduled task", encoding="utf-8")
    commands = []
    killed = []
    forgotten = []

    def task_command(command, check, stdout, stderr):
        commands.append(command)
        return startup.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(startup.subprocess, "run", task_command)
    monkeypatch.setattr(
        startup.instance,
        "probe",
        lambda port: instance.Instance(port=port, pid=48148, root=str(served.resolve())),
    )
    monkeypatch.setattr(startup.os, "kill", lambda pid, signal: killed.append((pid, signal)))
    monkeypatch.setattr(startup.instance, "forget", lambda port: forgotten.append(port))

    removed = startup.remove("summer-26")

    assert removed.name == "summer-26"
    assert (config_root / "servers.csv").read_text(encoding="utf-8").splitlines() == [
        "Name,Folder,Port"
    ]
    assert not script.exists()
    assert not launcher.exists()
    assert commands == [
        ["schtasks.exe", "/Delete", "/TN", "armoire summer-26", "/F"],
    ]
    assert killed == [(48148, startup.signal.SIGTERM)]
    assert forgotten == [8420]
    assert content.read_text(encoding="utf-8") == "notes"
    assert registry.read_text(encoding="utf-8") == "[[project]]\n"


def test_remove_preserves_cleanup_files_when_existing_task_cannot_be_deleted(tmp_path, monkeypatch):
    config_root = tmp_path / "cfg" / "armoire"
    system_root = tmp_path / "windows"
    served = tmp_path / "summer-26"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setenv("SystemRoot", str(system_root))
    records = config_root / "servers.csv"
    records.parent.mkdir(parents=True)
    records.write_text(
        f"Name,Folder,Port\nsummer-26,{served.resolve()},8420\n",
        encoding="utf-8",
    )
    script = config_root / "startup" / "summer-26.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("armoire serve ...", encoding="utf-8")
    task = system_root / "System32" / "Tasks" / "armoire summer-26"
    task.parent.mkdir(parents=True)
    task.write_text("scheduled task", encoding="utf-8")

    def task_command(command, check, stdout, stderr):
        return startup.subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(startup.subprocess, "run", task_command)

    result = CliRunner().invoke(main, ["startup", "remove", "summer-26"])

    assert result.exit_code == 1
    assert "could not delete Windows logon task" in result.output
    assert "summer-26" in records.read_text(encoding="utf-8")
    assert script.is_file()


def test_remove_preserves_metadata_when_startup_launcher_cannot_be_deleted(tmp_path, monkeypatch):
    config_root = tmp_path / "cfg" / "armoire"
    appdata = tmp_path / "roaming"
    served = tmp_path / "summer-26"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "windows"))
    records = config_root / "servers.csv"
    records.parent.mkdir(parents=True)
    records.write_text(
        f"Name,Folder,Port\nsummer-26,{served.resolve()},8420\n",
        encoding="utf-8",
    )
    launcher = (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "armoire summer-26.cmd"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("powershell ...", encoding="utf-8")
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda command, check, stdout, stderr: startup.subprocess.CompletedProcess(command, 1),
    )
    real_unlink = Path.unlink

    def deny_launcher(path, *args, **kwargs):
        if path == launcher:
            raise PermissionError("launcher is locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_launcher)

    result = CliRunner().invoke(main, ["startup", "remove", "summer-26"])

    assert result.exit_code == 1
    assert "could not remove legacy startup launcher" in result.output
    assert "summer-26" in records.read_text(encoding="utf-8")
    assert launcher.is_file()
