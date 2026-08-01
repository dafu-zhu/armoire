import pytest

from armoire.index import PathIndex, build_index


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("hi")
    (tmp_path / "docs" / "deep").mkdir()
    (tmp_path / "docs" / "deep" / "note.tex").write_text("x")
    venv = tmp_path / ".venv" / "lib" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "junk.py").write_text("noise")
    (tmp_path / "top.md").write_text("y")
    return tmp_path


def test_index_lists_files_as_relative_posix_paths(root):
    assert build_index(root) == ["docs/deep/note.tex", "docs/readme.md", "top.md"]


def test_index_prunes_ignored_trees(root):
    assert not any(".venv" in p for p in build_index(root))


def test_index_excludes_directories(root):
    assert "docs" not in build_index(root)


def test_path_index_is_empty_until_started(root):
    index = PathIndex(root)
    assert index.paths == []
    assert index.ready is False


def test_path_index_populates_after_start(root):
    index = PathIndex(root)
    index.start()
    index.wait()
    assert index.ready is True
    assert "docs/readme.md" in index.paths
