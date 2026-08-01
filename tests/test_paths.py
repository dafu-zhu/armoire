import sys

import pytest

from armoire.paths import PathOutsideRoot, resolve_in_root


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("hi")
    (tmp_path / "outside.txt").write_text("secret")
    inner = tmp_path / "docs"
    return inner


def test_resolves_a_child(root):
    assert resolve_in_root(root, "readme.md") == (root / "readme.md").resolve()


def test_empty_path_is_the_root_itself(root):
    assert resolve_in_root(root, "") == root.resolve()


def test_rejects_dotdot_escape(root):
    with pytest.raises(PathOutsideRoot):
        resolve_in_root(root, "../outside.txt")


def test_rejects_nested_dotdot_escape(root):
    with pytest.raises(PathOutsideRoot):
        resolve_in_root(root, "a/b/../../../outside.txt")


def test_rejects_absolute_path(root):
    absolute = "C:/Windows/win.ini" if sys.platform == "win32" else "/etc/passwd"
    with pytest.raises(PathOutsideRoot):
        resolve_in_root(root, absolute)


def test_rejects_null_byte(root):
    with pytest.raises(PathOutsideRoot):
        resolve_in_root(root, "readme.md\x00.png")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs admin on Windows")
def test_rejects_symlink_pointing_outside(root, tmp_path):
    (root / "escape").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(PathOutsideRoot):
        resolve_in_root(root, "escape")
