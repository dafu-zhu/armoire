from armoire import store
from armoire.dashboard import project_detail, project_rows
from armoire.projects import Project, Registry


def test_project_rows_reports_one_row_per_project_with_multiple_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    project = Project(name="Both", paths=("alpha", "beta"), category="x")
    registry = Registry(projects=[project], issues=[])

    rows = project_rows(tmp_path, registry)
    assert len(rows) == 1
    assert rows[0]["paths"] == ["alpha", "beta"]


def test_project_detail_with_all_bad_paths_yields_empty_file_list(tmp_path):
    project = Project(name="Ghosted", paths=("nowhere", "also-nowhere"))
    registry = Registry(projects=[project], issues=[])

    detail = project_detail(tmp_path, registry, "Ghosted")
    assert detail is not None
    assert detail["files"] == []


def test_project_detail_with_an_unknown_name_returns_none(tmp_path):
    registry = Registry(projects=[], issues=[])
    assert project_detail(tmp_path, registry, "Ghost") is None


def test_a_project_with_no_edges_is_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    assert project_rows(tmp_path, registry)[0]["isolated"] is True


def test_a_project_that_blocks_something_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(tmp_path, registry)}
    assert rows["A"]["isolated"] is False


def test_a_project_that_is_blocked_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(tmp_path, registry)}
    assert rows["B"]["isolated"] is False


def test_an_edge_to_an_unknown_project_does_not_make_it_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), blocked_by=("Ghost",), category="x")])
    # The edge is never drawn -- the blocker does not exist -- so A stands alone
    # on the canvas and belongs in a category container.
    assert project_rows(tmp_path, registry)[0]["isolated"] is True


def test_stored_status_overrides_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "done"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="active")])
    assert project_rows(tmp_path, registry)[0]["status"] == "done"


def test_the_registry_status_is_used_when_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(tmp_path, registry)[0]["status"] == "paused"


def test_a_corrupt_stored_status_falls_back_to_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(tmp_path, {"status": {"A": "nonsense"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(tmp_path, registry)[0]["status"] == "paused"


def test_rows_no_longer_carry_a_commit_count(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    row = project_rows(tmp_path, registry)[0]
    assert "commits" not in row and "last" not in row
