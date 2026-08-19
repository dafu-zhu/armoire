from armoire import store
from armoire.dashboard import project_detail, project_rows
from armoire.projects import Project, Registry


def test_project_rows_reports_one_row_per_project_with_multiple_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    project = Project(name="Both", paths=("alpha", "beta"), category="x")
    registry = Registry(projects=[project], issues=[])

    rows = project_rows(registry, store.state_path(tmp_path))
    assert len(rows) == 1
    assert rows[0]["paths"] == ["alpha", "beta"]


def test_a_habit_with_no_prerequisites_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="Practice", paths=("habit",), category="habit")])

    row = project_rows(registry, store.state_path(tmp_path))[0]

    assert row["is_habit"] is True
    assert row["habit_unlocked"] is True
    assert row["habit_locked_by"] == []


def test_a_habit_with_an_incomplete_prerequisite_is_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="Course", paths=("course",), category="course", status="active"),
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("Course",),
                category="habit",
            ),
        ]
    )

    row = {item["name"]: item for item in project_rows(registry, store.state_path(tmp_path))}[
        "Practice"
    ]

    assert row["habit_unlocked"] is False
    assert row["habit_locked_by"] == ["Course"]


def test_a_stored_done_prerequisite_unlocks_a_habit(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    state_file = store.state_path(tmp_path)
    store.write_state(state_file, {"status": {"Course": "done"}})
    registry = Registry(
        projects=[
            Project(name="Course", paths=("course",), category="course", status="active"),
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("Course",),
                category="habit",
            ),
        ]
    )

    row = {item["name"]: item for item in project_rows(registry, state_file)}["Practice"]

    assert row["habit_unlocked"] is True
    assert row["habit_locked_by"] == []


def test_a_habit_gate_does_not_connect_ordinary_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="Course", paths=("course",), category="course"),
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("Course",),
                category="habit",
            ),
        ]
    )

    rows = {item["name"]: item for item in project_rows(registry, store.state_path(tmp_path))}

    assert rows["Course"]["isolated"] is True
    assert rows["Practice"]["isolated"] is True


def test_a_habit_with_multiple_gates_waits_for_every_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="Done", paths=("done",), category="course", status="done"),
            Project(name="Open", paths=("open",), category="course", status="active"),
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("Done", "Open"),
                category="habit",
            ),
        ]
    )

    row = {item["name"]: item for item in project_rows(registry, store.state_path(tmp_path))}[
        "Practice"
    ]

    assert row["habit_unlocked"] is False
    assert row["habit_locked_by"] == ["Open"]


def test_a_habit_with_multiple_completed_gates_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="First", paths=("first",), category="course", status="done"),
            Project(name="Second", paths=("second",), category="course", status="done"),
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("First", "Second"),
                category="habit",
            ),
        ]
    )

    row = {item["name"]: item for item in project_rows(registry, store.state_path(tmp_path))}[
        "Practice"
    ]

    assert row["habit_unlocked"] is True
    assert row["habit_locked_by"] == []


def test_an_unknown_habit_gate_is_not_treated_as_done(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(
                name="Practice",
                paths=("habit",),
                blocked_by=("Ghost",),
                category="habit",
            )
        ]
    )

    row = project_rows(registry, store.state_path(tmp_path))[0]

    assert row["habit_unlocked"] is False
    assert row["habit_locked_by"] == ["Ghost"]


def test_project_detail_with_all_bad_paths_yields_empty_file_list(tmp_path):
    project = Project(name="Ghosted", paths=("nowhere", "also-nowhere"))
    registry = Registry(projects=[project], issues=[])

    detail = project_detail(tmp_path, registry, "Ghosted", store.state_path(tmp_path))
    assert detail is not None
    assert detail["files"] == []


def test_project_detail_with_an_unknown_name_returns_none(tmp_path):
    registry = Registry(projects=[], issues=[])
    assert project_detail(tmp_path, registry, "Ghost", store.state_path(tmp_path)) is None


def test_a_project_with_no_edges_is_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    assert project_rows(registry, store.state_path(tmp_path))[0]["isolated"] is True


def test_a_project_that_blocks_something_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(registry, store.state_path(tmp_path))}
    assert rows["A"]["isolated"] is False


def test_a_project_that_is_blocked_is_not_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(
        projects=[
            Project(name="A", paths=(), category="x"),
            Project(name="B", paths=(), blocked_by=("A",)),
        ]
    )
    rows = {r["name"]: r for r in project_rows(registry, store.state_path(tmp_path))}
    assert rows["B"]["isolated"] is False


def test_an_edge_to_an_unknown_project_does_not_make_it_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), blocked_by=("Ghost",), category="x")])
    # The edge is never drawn -- the blocker does not exist -- so A stands alone
    # on the canvas and belongs in a category container.
    assert project_rows(registry, store.state_path(tmp_path))[0]["isolated"] is True


def test_stored_status_overrides_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {"A": "done"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="active")])
    assert project_rows(registry, store.state_path(tmp_path))[0]["status"] == "done"


def test_the_registry_status_is_used_when_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(registry, store.state_path(tmp_path))[0]["status"] == "paused"


def test_a_corrupt_stored_status_falls_back_to_the_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    store.write_state(store.state_path(tmp_path), {"status": {"A": "nonsense"}})
    registry = Registry(projects=[Project(name="A", paths=(), category="x", status="paused")])
    assert project_rows(registry, store.state_path(tmp_path))[0]["status"] == "paused"


def test_rows_no_longer_carry_a_commit_count(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "config_root", lambda: tmp_path / "cfg")
    registry = Registry(projects=[Project(name="A", paths=(), category="x")])
    row = project_rows(registry, store.state_path(tmp_path))[0]
    assert "commits" not in row and "last" not in row


def test_project_detail_no_longer_carries_commits(tmp_path):
    """The recent-commits section was a useless feature -- project_detail
    must not spend a git-log call building a `commits` list nobody renders
    any more."""
    project = Project(name="A", paths=("nowhere",))
    registry = Registry(projects=[project], issues=[])
    detail = project_detail(tmp_path, registry, "A", store.state_path(tmp_path))
    assert "commits" not in detail
