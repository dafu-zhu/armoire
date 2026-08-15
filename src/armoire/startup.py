"""Removal support for legacy Windows-logon registrations."""

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


class RemovalError(Exception):
    """A confirmed legacy task still exists after deletion was attempted."""


HEADER = ["Name", "Folder", "Port"]


def _records_path() -> Path:
    return store.config_root() / "servers.csv"


def _scripts_dir() -> Path:
    return store.config_root() / "startup"


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


def _scheduled_task_path(name: str) -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return system_root / "System32" / "Tasks" / _task_name(name)


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

    task_path = _scheduled_task_path(match.name)
    try:
        task_path.stat()
    except FileNotFoundError:
        task_exists = False
    except OSError as error:
        raise RemovalError(
            f"could not confirm whether Windows logon task {_task_name(match.name)!r} exists; "
            "legacy registration was preserved"
        ) from error
    else:
        task_exists = True

    if task_exists:
        deleted = subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", _task_name(match.name), "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if deleted.returncode != 0:
            raise RemovalError(
                f"could not delete Windows logon task {_task_name(match.name)!r}; "
                "legacy registration was preserved"
            )

    for path, label in (
        (_startup_launcher_path(match.name), "legacy startup launcher"),
        (_script_path(match.name), "legacy startup script"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise RemovalError(
                f"could not remove {label} {str(path)!r}; legacy registration was preserved"
            ) from error
    _write_records([record for record in records if record != match])

    found = instance.probe(match.port)
    if found is not None and _same_folder(found.root, match.folder):
        with contextlib.suppress(ProcessLookupError):
            os.kill(found.pid, signal.SIGTERM)
        instance.forget(match.port)

    return match
