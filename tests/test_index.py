import os
from pathlib import Path

import pytest

import armoire.index
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


def test_path_index_start_is_idempotent(root):
    """Calling start() twice must not create a second thread."""
    index = PathIndex(root)
    index.start()
    first_thread = index._thread
    index.start()
    assert index._thread is first_thread


def test_ignored_trees_are_never_descended_into(root, monkeypatch):
    """Pruning must happen before descent, not by filtering after the walk."""
    visited = []
    real_walk = os.walk

    def spy(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited.append(dirpath)
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(armoire.index.os, "walk", spy)
    build_index(root)

    assert visited, "the spy never fired — the walk did not go through os.walk"
    assert not any(".venv" in Path(p).parts for p in visited)


def test_path_index_resolves_even_if_build_fails(root, monkeypatch):
    """A stranded index is worse than an empty one."""

    def failing_build(root):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(armoire.index, "build_index", failing_build)
    index = PathIndex(root)
    index.start()
    index.wait()
    assert index.ready is True
    assert index.paths == []
