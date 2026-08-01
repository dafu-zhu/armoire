import pytest

from armoire.ignore import is_ignored
from armoire.paths import PathOutsideRoot
from armoire.scanner import list_dir


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "Data").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "readme.md").write_text("hello")
    (tmp_path / "notes.tex").write_text("\\documentclass{article}")
    (tmp_path / "Makefile").write_text("all:")
    return tmp_path


def test_ignores_known_noise():
    assert is_ignored(".venv")
    assert is_ignored("site-packages")
    assert is_ignored("__pycache__")
    assert not is_ignored("docs")
    assert not is_ignored("venv")


def test_lists_dirs_and_files_separately(root):
    dirs, files = list_dir(root, "")
    assert [d.name for d in dirs] == ["Data", "docs"]
    assert [f.name for f in files] == ["Makefile", "notes.tex", "readme.md"]


def test_sorting_is_case_insensitive(root):
    dirs, _ = list_dir(root, "")
    assert [d.name for d in dirs] == ["Data", "docs"]


def test_ignored_dirs_are_absent(root):
    dirs, _ = list_dir(root, "")
    names = [d.name for d in dirs]
    assert ".venv" not in names
    assert "__pycache__" not in names


def test_extension_has_no_dot_and_is_lowercased(root):
    _, files = list_dir(root, "")
    by_name = {f.name: f for f in files}
    assert by_name["readme.md"].ext == "md"
    assert by_name["Makefile"].ext == ""


def test_file_metadata_is_populated(root):
    _, files = list_dir(root, "")
    entry = next(f for f in files if f.name == "readme.md")
    assert entry.size == 5
    assert entry.mtime > 0
    assert entry.is_dir is False


def test_refuses_to_list_outside_root(root):
    with pytest.raises(PathOutsideRoot):
        list_dir(root, "../..")


def test_missing_directory_raises(root):
    with pytest.raises(FileNotFoundError):
        list_dir(root, "nope")
