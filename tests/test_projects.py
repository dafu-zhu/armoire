import pytest

from armoire.projects import RegistryError, load_registry

VALID = """
[[project]]
name = "0DTE"
paths = ["research/0dte"]
blocked_by = ["FINM 320"]
category = "research"
due = 2026-08-17
note = "arXiv preprint"

[[project]]
name = "FINM 320"
paths = ["learning/finm32000"]
"""


def write(root, text):
    (root / "armoire.toml").write_text(text, encoding="utf-8")
    for name in ("research/0dte", "learning/finm32000"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def test_no_registry_returns_none(tmp_path):
    assert load_registry(tmp_path) is None


def test_parses_projects_in_declaration_order(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    assert [p.name for p in registry.projects] == ["0DTE", "FINM 320"]


def test_optional_fields_default_to_none_or_empty(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    finm = registry.projects[1]
    assert finm.blocked_by == ()
    assert finm.category is None
    assert finm.due is None
    assert finm.note is None


def test_due_is_an_iso_string_not_a_date(tmp_path):
    import json

    registry = load_registry(write(tmp_path, VALID))
    assert registry.projects[0].due == "2026-08-17"
    json.dumps(registry.projects[0].due)


def test_paths_is_a_tuple_of_strings(tmp_path):
    registry = load_registry(write(tmp_path, VALID))
    assert registry.projects[0].paths == ("research/0dte",)


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, "[[project]\nname = "))


def test_missing_name_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, '[[project]]\npaths = ["a"]\n'))


def test_missing_paths_raises(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, '[[project]]\nname = "A"\n'))


def test_duplicate_name_raises_naming_both(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["x"]\n\n[[project]]\nname = "A"\npaths = ["y"]\n'
    with pytest.raises(RegistryError, match="A"):
        load_registry(write(tmp_path, text))


def test_unknown_blocked_by_is_an_issue_not_an_error(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["Ghost"]\n'
    registry = load_registry(write(tmp_path, text))
    assert [p.name for p in registry.projects] == ["A"]
    assert any("Ghost" in issue for issue in registry.issues)


def test_cycle_is_reported_with_its_path(tmp_path):
    text = (
        '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["B"]\n\n'
        '[[project]]\nname = "B"\npaths = ["research/0dte"]\nblocked_by = ["A"]\n'
    )
    registry = load_registry(write(tmp_path, text))
    assert len(registry.projects) == 2
    cycle_issues = [i for i in registry.issues if "cycle" in i.lower()]
    assert len(cycle_issues) == 1
    # Every issue must be attributable: downstream splits on the first ":"
    # and matches the left side against project names.
    owner = cycle_issues[0].split(":", 1)[0].strip()
    assert owner in {p.name for p in registry.projects}
    assert "A" in cycle_issues[0] and "B" in cycle_issues[0]


def test_missing_path_is_an_issue(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["nowhere"]\n'
    registry = load_registry(write(tmp_path, text))
    assert any("nowhere" in issue for issue in registry.issues)


def test_a_path_escaping_the_root_is_an_issue_even_when_it_exists(tmp_path):
    """The old check only asked whether the path existed, so an escaping path
    that did exist was silently accepted."""
    (tmp_path / "outside").mkdir()
    root = tmp_path / "a" / "b"
    root.mkdir(parents=True)
    (root / "armoire.toml").write_text(
        '[[project]]\nname = "Evil"\npaths = ["../../outside"]\n', encoding="utf-8"
    )
    registry = load_registry(root)
    assert (root / "../../outside").exists()
    issues = [i for i in registry.issues if "Evil" in i]
    assert issues, "an escaping path must be reported"
    assert "escape" in issues[0].lower()


def test_every_issue_is_attributable_to_a_real_project(tmp_path):
    """Downstream marks the graph by splitting each issue on its first ':'."""
    text = (
        '[[project]]\nname = "A"\npaths = ["nowhere"]\nblocked_by = ["Ghost", "B"]\n\n'
        '[[project]]\nname = "B"\npaths = ["research/0dte"]\nblocked_by = ["A"]\n'
    )
    registry = load_registry(write(tmp_path, text))
    assert registry.issues
    names = {p.name for p in registry.projects}
    for issue in registry.issues:
        assert issue.split(":", 1)[0].strip() in names, issue


def test_a_project_blocking_itself_is_a_cycle(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["A"]\n'
    registry = load_registry(write(tmp_path, text))
    assert any("cycle" in i.lower() for i in registry.issues)
