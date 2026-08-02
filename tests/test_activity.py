import subprocess

import pytest

from armoire.activity import recent_commits
from conftest import _git as git


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha" / "a.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "first alpha commit")
    (tmp_path / "alpha" / "a.txt").write_text("2", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "second alpha commit")
    (tmp_path / "beta" / "b.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "only beta commit")
    return tmp_path


def test_recent_commits_returns_subjects_newest_first(repo):
    entries = recent_commits(repo, "alpha")
    assert [e["subject"] for e in entries] == ["second alpha commit", "first alpha commit"]
    assert all(len(e["sha"]) >= 7 for e in entries)
    assert all(isinstance(e["when"], float) for e in entries)


def test_recent_commits_honours_the_limit(repo):
    assert len(recent_commits(repo, "alpha", limit=1)) == 1


def test_activity_does_not_read_outside_the_served_root(tmp_path):
    """A declared path that escapes must yield nothing, not another repo's history."""
    outside = tmp_path / "secret"
    outside.mkdir()
    git(outside, "init", "-q", "-b", "main")
    (outside / "f.txt").write_text("x", encoding="utf-8")
    git(outside, "add", "-A")
    git(outside, "commit", "-qm", "confidential subject")
    served = tmp_path / "served"
    served.mkdir()
    assert recent_commits(served, "../secret") == []


def test_a_decode_failure_does_not_raise(monkeypatch, repo):
    """A commit subject with bytes invalid in the platform's default encoding
    makes subprocess.run raise UnicodeDecodeError -- a ValueError -- while
    decoding stdout under text=True. Activity is a nice-to-have; it must not
    take the roadmap down with it."""

    def boom(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(subprocess, "run", boom)
    assert recent_commits(repo, "alpha") == []
