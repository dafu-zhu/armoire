import sys

from armoire import instance, startup, store


def test_enable_startup_creates_csv_script_and_windows_task(tmp_path, monkeypatch):
    config_root = tmp_path / "cfg" / "armoire"
    served = tmp_path / "summer-26"
    served.mkdir()
    commands = []
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda command, check, stdout, stderr: commands.append(
            {"command": command, "stdout": stdout, "stderr": stderr}
        ),
    )

    record = startup.enable(served, 8420, None)

    assert record.name == "summer-26"
    assert (config_root / "servers.csv").read_text(encoding="utf-8").splitlines() == [
        "Name,Folder,Port",
        f"summer-26,{served.resolve()},8420",
    ]
    script = config_root / "startup" / "summer-26.ps1"
    assert script.read_text(encoding="utf-8") == (
        f"& '{sys.executable}' -m armoire.cli serve '{served.resolve()}' -df -p 8420\n"
    )
    assert commands == [
        {
            "command": [
                "schtasks.exe",
                "/Create",
                "/TN",
                "armoire summer-26",
                "/SC",
                "ONLOGON",
                "/TR",
                (
                    "powershell.exe -NoProfile -ExecutionPolicy Bypass "
                    f'-WindowStyle Hidden -File "{script}"'
                ),
                "/F",
            ],
            "stdout": startup.subprocess.DEVNULL,
            "stderr": startup.subprocess.DEVNULL,
        }
    ]


def test_enable_startup_falls_back_to_user_startup_folder_when_schtasks_is_denied(
    tmp_path, monkeypatch
):
    config_root = tmp_path / "cfg" / "armoire"
    appdata = tmp_path / "roaming"
    served = tmp_path / "summer-26"
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setenv("APPDATA", str(appdata))

    def denied(command, check, stdout, stderr):
        raise startup.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(startup.subprocess, "run", denied)

    startup.enable(served, 8420, None)

    launcher = (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "armoire summer-26.cmd"
    )
    script = config_root / "startup" / "summer-26.ps1"
    assert launcher.read_text(encoding="utf-8") == (
        "@echo off\n"
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}"\n'
    )


def test_remove_deletes_task_and_stops_matching_server_without_touching_folder_or_registry(
    tmp_path, monkeypatch
):
    config_root = tmp_path / "cfg" / "armoire"
    appdata = tmp_path / "roaming"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    monkeypatch.setenv("APPDATA", str(appdata))
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
    commands = []
    killed = []
    forgotten = []
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda command, check, stdout, stderr: commands.append(command),
    )
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
    assert commands == [["schtasks.exe", "/Delete", "/TN", "armoire summer-26", "/F"]]
    assert killed == [(48148, startup.signal.SIGTERM)]
    assert forgotten == [8420]
    assert content.read_text(encoding="utf-8") == "notes"
    assert registry.read_text(encoding="utf-8") == "[[project]]\n"
