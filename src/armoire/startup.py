"""Windows logon startup registrations for armoire."""

import contextlib
import csv
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from armoire import instance, store


@dataclass(frozen=True)
class Record:
    name: str
    folder: Path
    port: int


HEADER = ["Name", "Folder", "Port"]


def _records_path() -> Path:
    return store.config_root() / "servers.csv"


def _scripts_dir() -> Path:
    return store.config_root() / "startup"


def _default_name(folder: Path) -> str:
    return folder.name or store.folder_key(folder)


def _script_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-")
    return _scripts_dir() / f"{safe or 'folder'}.ps1"


def _startup_launcher_path(name: str) -> Path:
    base = Path(os.environ.get("APPDATA", str(store.config_root().parent)))
    return (
        base
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / f"{_task_name(name)}.cmd"
    )


def _task_name(name: str) -> str:
    return f"armoire {name}"


def _same_folder(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _read_records() -> list[Record]:
    path = _records_path()
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        rows = csv.DictReader(stream)
        records = []
        for row in rows:
            try:
                records.append(
                    Record(
                        name=row["Name"],
                        folder=Path(row["Folder"]),
                        port=int(row["Port"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return records


def _write_records(records: list[Record]) -> None:
    path = _records_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        for record in records:
            writer.writerow([record.name, str(record.folder), record.port])


def enable(folder: Path, port: int, name: str | None = None) -> Record:
    root = folder.resolve()
    record = Record(name=name or _default_name(root), folder=root, port=port)
    records = [
        existing
        for existing in _read_records()
        if existing.name != record.name and existing.folder.resolve() != root
    ]
    records.append(record)
    _write_records(records)

    script = _script_path(record.name)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'armoire serve "{root}" -df -p {port}\n', encoding="utf-8")

    launcher = (
        "powershell.exe -NoProfile -ExecutionPolicy Bypass "
        f'-WindowStyle Hidden -File "{script}"'
    )
    try:
        subprocess.run(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                _task_name(record.name),
                "/SC",
                "ONLOGON",
                "/TR",
                launcher,
                "/F",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        fallback = _startup_launcher_path(record.name)
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(f"@echo off\n{launcher}\n", encoding="utf-8")
    return record


def remove(target: str) -> Record:
    records = _read_records()
    match = next(
        (
            record
            for record in records
            if record.name == target or _same_folder(record.folder, target)
        ),
        None,
    )
    if match is None:
        raise ValueError(f"no startup registration for {target}")

    _write_records([record for record in records if record != match])
    with contextlib.suppress(OSError):
        _script_path(match.name).unlink()
    with contextlib.suppress(OSError):
        _startup_launcher_path(match.name).unlink()
    subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", _task_name(match.name), "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    found = instance.probe(match.port)
    if found is not None and _same_folder(found.root, match.folder):
        with contextlib.suppress(ProcessLookupError):
            os.kill(found.pid, signal.SIGTERM)
        instance.forget(match.port)

    return match
