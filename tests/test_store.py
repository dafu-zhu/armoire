import json
import os
import sys
import threading
from pathlib import Path

import pytest

from armoire import store


def test_windows_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert store.config_root() == tmp_path / "Roaming" / "armoire"


def test_macos_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / "Library" / "Application Support" / "armoire"


def test_linux_prefers_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert store.config_root() == tmp_path / "cfg" / "armoire"


def test_linux_falls_back_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / ".config" / "armoire"


def test_windows_falls_back_when_appdata_is_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(store, "_home", lambda: tmp_path)
    assert store.config_root() == tmp_path / "AppData" / "Roaming" / "armoire"


def test_the_key_carries_the_folder_name(tmp_path):
    folder = tmp_path / "summer-26"
    folder.mkdir()
    assert store.folder_key(folder).startswith("summer-26-")


def test_the_key_is_stable_across_calls(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    assert store.folder_key(folder) == store.folder_key(folder)


def test_same_basename_in_different_places_gets_different_keys(tmp_path):
    a = tmp_path / "one" / "docs"
    b = tmp_path / "two" / "docs"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert store.folder_key(a) != store.folder_key(b)


def test_the_key_is_filesystem_safe(tmp_path):
    folder = tmp_path / "a b:c*d"
    key = store.folder_key(folder)
    assert all(c.isalnum() or c in "-_" for c in key), key


def test_a_folder_with_no_usable_name_still_gets_a_key(tmp_path):
    folder = tmp_path / "???"
    key = store.folder_key(folder)
    # The sanitised tail is empty, so the key is the hash alone -- never "".
    assert len(key) >= 8


def test_reading_state_that_does_not_exist_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    assert store.read_state(store.state_path(tmp_path)) == {}


def test_state_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {"A": "done"}})
    assert store.read_state(store.state_path(tmp_path)) == {"status": {"A": "done"}}


def test_corrupt_state_reads_as_empty_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {}})
    store.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert store.read_state(store.state_path(tmp_path)) == {}


def test_state_json_that_is_not_an_object_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {})
    store.state_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    # json.loads succeeds and yields a list, which every caller would then
    # .get() against and crash on.
    assert store.read_state(store.state_path(tmp_path)) == {}


def test_writing_state_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {"A": "done"}})
    names = sorted(p.name for p in store.folder_dir(tmp_path).iterdir())
    assert names == ["state.json"]


def test_a_second_write_replaces_rather_than_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {"A": "done"}})
    store.write_state(store.state_path(tmp_path), {"status": {"B": "paused"}})
    assert json.loads(store.state_path(tmp_path).read_text(encoding="utf-8")) == {
        "status": {"B": "paused"}
    }


def test_two_overlapping_writes_each_rename_their_own_temporary_file(tmp_path, monkeypatch):
    """The temporary file must be unique per writer, not per folder.

    A fixed name (state.json.tmp) lives in a directory keyed only by the
    served folder, so both writers open the very same path. The second's
    content lands on top of the first's, and the rename each writer then
    performs publishes whatever is in that shared file -- the other writer's
    state, not its own. That is the failure this pins: what a writer renames
    into place must be what that writer wrote.

    The barrier makes the interleaving certain rather than merely likely:
    neither thread renames until both have finished writing, which is exactly
    what a shared temporary name cannot survive. It is scoped to writes of
    the state file so no unrelated os.replace in the process can stumble into
    it.

    Windows deserves a note, because it is where this suite runs and where
    the failure is quietest. A rename there is performed against an open
    handle, and a handle survives a rename: both writers' os.replace calls
    return successfully even though only one file ever existed, so the shared
    temporary name shows up purely as lost content, with no exception
    anywhere to notice. `failures` is still asserted -- on POSIX the second
    rename finds nothing and raises FileNotFoundError, which would 500 that
    request -- but it is not what carries this test.
    """
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    state_file = store.state_path(tmp_path)
    both_written = threading.Barrier(2)
    real_replace = os.replace
    renamed = []
    guard = threading.Lock()

    def replace(source, destination):
        if str(destination).endswith(store.STATE_FILE):
            both_written.wait(timeout=10)
            with guard:
                renamed.append((str(source), Path(source).read_text(encoding="utf-8")))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace)

    failures = []

    def write(name):
        try:
            store.write_state(state_file, {"status": {name: "done"}})
        except BaseException as exc:  # noqa: BLE001 -- reported, not swallowed
            failures.append(f"{name}: {exc!r}")

    writers = [threading.Thread(target=write, args=(name,)) for name in ("A", "B")]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=15)

    assert len(renamed) == 2, renamed
    assert len({source for source, _ in renamed}) == 2, renamed
    published = [json.loads(text)["status"] for _, text in renamed]
    assert {"A": "done"} in published, published
    assert {"B": "done"} in published, published
    assert not failures, failures
    # Two edits to the same key: last write wins between them. What may not
    # happen is either writer losing its own content on the way to disk.
    assert json.loads(state_file.read_text(encoding="utf-8"))["status"] in (
        {"A": "done"},
        {"B": "done"},
    )
    assert sorted(p.name for p in store.folder_dir(tmp_path).iterdir()) == [store.STATE_FILE]


def test_a_write_that_fails_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    """mkstemp names are unique, so a failure that left its temporary behind
    leaves a fresh orphan per attempt rather than one reusable file."""
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    state_file = store.state_path(tmp_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    def explode(source, destination):
        raise OSError("no rename today")

    monkeypatch.setattr(os, "replace", explode)
    try:
        store.write_state(state_file, {"status": {"A": "done"}})
    except OSError:
        pass
    else:
        raise AssertionError("write_state swallowed the failed rename")
    assert list(store.folder_dir(tmp_path).iterdir()) == []


def test_writes_inside_does_not_match_sibling_prefix(tmp_path, monkeypatch):
    # Prevent naive string-prefix bug: /a/bc should not match /a/b
    config = tmp_path / "armoire"
    served = tmp_path / "armoir"  # sibling with matching prefix but different path
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: config)
    assert store.writes_inside(served) is False


def test_writes_inside_is_detected_inside_a_served_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    assert store.writes_inside(tmp_path) is True


def test_writes_inside_is_not_inside_an_unrelated_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    served = tmp_path / "served"
    served.mkdir()
    assert store.writes_inside(served) is False


def test_writes_inside_catches_the_descendant_case(tmp_path, monkeypatch):
    """The exact scenario from review: config_root() sits *above* the served
    folder (the served folder is a descendant of the store, e.g. serving
    config_root()'s own "folders" directory). The weaker question -- does
    config_root() itself sit inside the served folder -- answers False here,
    because the containment runs the other way. But folder_dir(folder) is
    keyed off folder's own hash and still lands inside folder, which is what
    prepare_store and the status endpoint actually need answered, so the
    predicate that asks about the write target must answer True.

    The contrast is asserted directly rather than through a second predicate:
    config_root() is verifiably not inside the served folder here, and
    writes_inside says True anyway."""
    config_root = tmp_path / "cfg" / "armoire"
    monkeypatch.setattr(store, "config_root", lambda: config_root)
    served = config_root / "folders"
    served.mkdir(parents=True)
    assert not config_root.is_relative_to(served)
    assert store.writes_inside(served) is True


def test_open_in_editor_uses_startfile_on_windows(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    # raising=False: os.startfile does not exist on Linux or macOS, so on
    # every non-Windows machine this is creating the attribute rather than
    # replacing one. Without it, this test cannot run anywhere but Windows.
    monkeypatch.setattr(os, "startfile", lambda p: seen.append(p), raising=False)
    store.open_in_editor(target)
    assert seen == [target]


def test_open_in_editor_uses_open_on_macos(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "darwin")

    class Handle:
        def wait(self, timeout):
            assert timeout == 0.25
            return 0

    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: (seen.append(argv), Handle())[1])
    store.open_in_editor(target)
    assert seen == [["open", str(target)]]


def test_open_in_editor_uses_xdg_open_elsewhere(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")
    seen = []
    monkeypatch.setattr(sys, "platform", "linux")

    class Handle:
        def wait(self, timeout):
            assert timeout == 0.25
            return 0

    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: (seen.append(argv), Handle())[1])
    store.open_in_editor(target)
    assert seen == [["xdg-open", str(target)]]


def test_open_in_editor_stops_waiting_while_the_launcher_is_still_running(tmp_path, monkeypatch):
    """A GUI editor can outlive the request that launched it. A bounded wait
    may inspect a quick launcher failure, but must abandon a live process."""
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")

    class Handle:
        def __init__(self):
            self.timeouts = []

        def wait(self, timeout):
            self.timeouts.append(timeout)
            raise store.subprocess.TimeoutExpired("xdg-open", timeout)

    handle = Handle()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: handle)
    store.open_in_editor(target)
    assert handle.timeouts == [0.25]


def test_open_in_editor_reports_a_nonzero_launcher_exit(tmp_path, monkeypatch):
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")

    class Handle:
        def wait(self, timeout):
            return 3

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", lambda argv: Handle())

    with pytest.raises(OSError, match="xdg-open exited with status 3"):
        store.open_in_editor(target)


def test_open_in_editor_propagates_a_launch_failure(tmp_path, monkeypatch):
    """No handler registered, or no xdg-open on the box. The endpoint turns
    this into a 500 the UI can show, so it must not be swallowed here."""
    target = tmp_path / "registry.toml"
    target.write_text("", encoding="utf-8")

    def boom(argv):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(store.subprocess, "Popen", boom)
    with pytest.raises(OSError):
        store.open_in_editor(target)
