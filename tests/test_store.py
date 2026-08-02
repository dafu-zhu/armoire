import json
import sys

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
    assert store.read_state(tmp_path) == {}


def test_state_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    assert store.read_state(tmp_path) == {"status": {"A": "done"}}


def test_corrupt_state_reads_as_empty_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {}})
    store.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert store.read_state(tmp_path) == {}


def test_state_json_that_is_not_an_object_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {})
    store.state_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    # json.loads succeeds and yields a list, which every caller would then
    # .get() against and crash on.
    assert store.read_state(tmp_path) == {}


def test_writing_state_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    names = sorted(p.name for p in store.folder_dir(tmp_path).iterdir())
    assert names == ["state.json"]


def test_a_second_write_replaces_rather_than_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    store.write_state(tmp_path, {"status": {"B": "paused"}})
    assert json.loads(store.state_path(tmp_path).read_text(encoding="utf-8")) == {
        "status": {"B": "paused"}
    }


def test_the_store_does_not_match_sibling_prefix(tmp_path, monkeypatch):
    # Prevent naive string-prefix bug: /a/bc should not match /a/b
    config = tmp_path / "armoire"
    served = tmp_path / "armoir"  # sibling with matching prefix but different path
    served.mkdir()
    monkeypatch.setattr(store, "config_root", lambda: config)
    assert store.store_is_inside(served) is False


def test_the_store_is_detected_inside_a_served_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    assert store.store_is_inside(tmp_path) is True


def test_the_store_is_not_inside_an_unrelated_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg" / "armoire")
    served = tmp_path / "served"
    served.mkdir()
    assert store.store_is_inside(served) is False
