from pathlib import Path
from unittest.mock import patch

import pytest

from armoire.ignore import is_ignored
from armoire.paths import PathOutsideRoot
from armoire.scanner import Entry, _sort_key, list_dir


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


def test_sort_key_breaks_case_ties_deterministically():
    """A real filesystem cannot hold these three at once, so the key is tested directly."""
    names = ["readme.txt", "Readme.txt", "README.txt"]
    entries = [Entry(name=n, is_dir=False, size=0, mtime=1.0, ext="txt") for n in names]
    assert [e.name for e in sorted(entries, key=_sort_key)] == [
        "README.txt",
        "Readme.txt",
        "readme.txt",
    ]


def test_oserror_skips_inaccessible_entries(root):
    """Entries that raise OSError are silently skipped from results."""
    # Create a file that we'll make inaccessible
    (root / "accessible.txt").write_text("hello")
    (root / "inaccessible.txt").write_text("world")

    # Patch Path.stat to raise OSError for the inaccessible file
    original_stat = Path.stat

    def stat_with_failure(self, *, follow_symlinks=True):
        if self.name == "inaccessible.txt":
            raise OSError("Permission denied")
        return original_stat(self, follow_symlinks=follow_symlinks)

    with patch.object(Path, "stat", stat_with_failure):
        _, files = list_dir(root, "")

    file_names = [f.name for f in files]
    assert "accessible.txt" in file_names
    assert "inaccessible.txt" not in file_names


def test_list_dir_does_not_inherit_iterdir_order(root):
    """list_dir sorts results instead of passing through iterdir's order."""
    # Create a subdirectory for this test to avoid fixture files
    test_dir = root / "sorttest"
    test_dir.mkdir()
    (test_dir / "z.txt").write_text("z")
    (test_dir / "y.txt").write_text("y")
    (test_dir / "x.txt").write_text("x")

    # Monkeypatch iterdir to yield them in reverse-sorted order (z, y, x)
    original_iterdir = Path.iterdir

    def iterdir_reverse(self):
        """Yield entries in reverse-sorted order."""
        if self == test_dir:
            # Get all real children and reverse-sort them
            children = sorted(original_iterdir(self), key=lambda p: p.name, reverse=True)
            yield from children
        else:
            yield from original_iterdir(self)

    with patch.object(Path, "iterdir", iterdir_reverse):
        _, files = list_dir(root, "sorttest")

    # Despite iterdir returning them in reverse order (z, y, x),
    # list_dir must sort them (x, y, z)
    file_names = [f.name for f in files]
    assert file_names == ["x.txt", "y.txt", "z.txt"]
