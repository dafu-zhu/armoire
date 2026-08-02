from armoire.dashboard import project_detail, project_rows
from armoire.projects import Project, Registry
from conftest import _git as git


def test_project_rows_merges_activity_across_two_paths(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha" / "a.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "alpha commit")
    (tmp_path / "beta" / "b.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "beta commit")

    project = Project(name="Both", paths=("alpha", "beta"))
    registry = Registry(projects=[project], issues=[])

    rows = project_rows(tmp_path, registry)
    assert len(rows) == 1
    assert rows[0]["commits"] == 2
    assert rows[0]["last"] is not None


def test_project_detail_with_all_bad_paths_yields_empty_file_list(tmp_path):
    project = Project(name="Ghosted", paths=("nowhere", "also-nowhere"))
    registry = Registry(projects=[project], issues=[])

    detail = project_detail(tmp_path, registry, "Ghosted")
    assert detail is not None
    assert detail["files"] == []


def test_project_detail_with_an_unknown_name_returns_none(tmp_path):
    registry = Registry(projects=[], issues=[])
    assert project_detail(tmp_path, registry, "Ghost") is None
