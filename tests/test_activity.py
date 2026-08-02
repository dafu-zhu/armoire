import subprocess

import pytest

from armoire.activity import Activity, activity_for, recent_commits
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


def test_counts_commits_scoped_to_the_path(repo):
    assert activity_for(repo, "alpha").commits == 2
    assert activity_for(repo, "beta").commits == 1


def test_reports_a_last_commit_timestamp(repo):
    result = activity_for(repo, "alpha")
    assert result.last is not None and result.last > 0


def test_a_path_with_no_history_reports_zero(repo):
    (repo / "gamma").mkdir()
    result = activity_for(repo, "gamma")
    assert result.commits == 0


def test_a_missing_path_reports_zero_without_raising(repo):
    assert activity_for(repo, "nowhere").commits == 0


def test_outside_a_repository_reports_zero_without_raising(tmp_path):
    (tmp_path / "plain").mkdir()
    assert activity_for(tmp_path, "plain").commits == 0


def test_outside_a_repository_still_reports_a_last_touch_from_mtimes(tmp_path):
    """Not every folder is in git; the spec requires an mtime fallback."""
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "f.txt").write_text("x", encoding="utf-8")
    result = activity_for(tmp_path, "plain")
    assert result.commits == 0
    assert result.last is not None and result.last > 0


def test_an_empty_untracked_folder_reports_no_last_touch(tmp_path):
    (tmp_path / "hollow").mkdir()
    assert activity_for(tmp_path, "hollow").last is None


def test_recent_commits_returns_subjects_newest_first(repo):
    entries = recent_commits(repo, "alpha")
    assert [e["subject"] for e in entries] == ["second alpha commit", "first alpha commit"]
    assert all(len(e["sha"]) >= 7 for e in entries)
    assert all(isinstance(e["when"], float) for e in entries)


def test_recent_commits_honours_the_limit(repo):
    assert len(recent_commits(repo, "alpha", limit=1)) == 1


def test_a_submodule_is_read_from_its_own_repository(repo, tmp_path_factory):
    """The parent repository's log cannot see inside a submodule."""
    inner = tmp_path_factory.mktemp("inner")
    git(inner, "init", "-q", "-b", "main")
    (inner / "x.txt").write_text("1", encoding="utf-8")
    git(inner, "add", "-A")
    git(inner, "commit", "-qm", "inner commit one")
    (inner / "x.txt").write_text("2", encoding="utf-8")
    git(inner, "add", "-A")
    git(inner, "commit", "-qm", "inner commit two")

    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "sub")
    git(repo, "commit", "-qm", "add submodule")

    assert activity_for(repo, "sub").commits == 2


def test_the_mtime_scan_reports_unknown_past_the_cap(tmp_path, monkeypatch):
    """rglob order has nothing to do with mtime; a truncated scan cannot trust
    the newest-so-far value, so it must admit it does not know rather than
    reporting a possibly-wrong "last touched"."""
    monkeypatch.setattr("armoire.activity.MAX_SCAN_FILES", 3)
    (tmp_path / "many").mkdir()
    for i in range(5):
        (tmp_path / "many" / f"f{i}.txt").write_text("x", encoding="utf-8")
    result = activity_for(tmp_path, "many")
    assert result.last is None


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
    assert activity_for(served, "../secret") == Activity(commits=0, last=None)
    assert recent_commits(served, "../secret") == []


def test_a_decode_failure_does_not_raise(monkeypatch, repo):
    """A commit subject with bytes invalid in the platform's default encoding
    makes subprocess.run raise UnicodeDecodeError -- a ValueError -- while
    decoding stdout under text=True. Activity is a nice-to-have; it must not
    take the roadmap down with it."""

    def boom(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(subprocess, "run", boom)
    assert activity_for(repo, "alpha").commits == 0
    assert recent_commits(repo, "alpha") == []
