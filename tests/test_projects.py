import pytest

from armoire.projects import STATUSES, RegistryError, load_registry

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
category = "learning"
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
    # FINM 320 carries a category (required by the placement rule -- a project
    # with neither blocked_by nor category cannot be placed), so it is no
    # longer the example of that field defaulting to None.
    assert finm.category == "learning"
    assert finm.due is None
    assert finm.note is None


def test_category_defaults_to_none_when_satisfied_via_blocked_by(tmp_path):
    """FINM 320 above no longer demonstrates category defaulting to None,
    since it now carries one to satisfy the placement rule. This project
    satisfies the same rule via blocked_by instead, so it is the one that
    still proves category is None when the key is absent."""
    write(
        tmp_path,
        '[[project]]\nname = "A"\npaths = ["research/0dte"]\ncategory = "x"\n'
        '[[project]]\nname = "B"\npaths = ["learning/finm32000"]\nblocked_by = ["A"]\n',
    )
    registry = load_registry(tmp_path)
    b = registry.projects[1]
    assert b.category is None


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


def test_a_single_bracket_project_table_raises_rather_than_escaping(tmp_path):
    """`[project]` is the single most likely typo in the whole file, and it does
    not parse to "a list containing a non-dict": TOML makes it a string-keyed
    table, so iterating it yields the key strings "name" and "paths" and the
    first `.get` used to escape as a raw AttributeError."""
    text = '[project]\nname = "A"\npaths = ["research/0dte"]\n'
    with pytest.raises(RegistryError, match=r"\[\[project\]\]"):
        load_registry(write(tmp_path, text))


def test_a_scalar_project_key_raises_rather_than_escaping(tmp_path):
    """`project = "A"` iterates to single characters, so it too reached `.get`."""
    with pytest.raises(RegistryError, match="project"):
        load_registry(write(tmp_path, 'project = "A"\n'))


def test_a_project_entry_that_is_not_a_table_names_its_position(tmp_path):
    with pytest.raises(RegistryError, match="#2"):
        load_registry(write(tmp_path, 'project = [{ name = "A", paths = ["x"] }, "B"]\n'))


def test_non_list_paths_raises_naming_the_project(tmp_path):
    """`tuple(str(i) for i in 5)` used to escape as a raw TypeError."""
    with pytest.raises(RegistryError, match="A"):
        load_registry(write(tmp_path, '[[project]]\nname = "A"\npaths = 5\n'))


def test_non_list_blocked_by_raises_naming_the_project(tmp_path):
    with pytest.raises(RegistryError, match="A"):
        load_registry(write(tmp_path, '[[project]]\nname = "A"\npaths = ["x"]\nblocked_by = 7\n'))


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
        '[[project]]\nname = "Evil"\npaths = ["../../outside"]\ncategory = "x"\n',
        encoding="utf-8",
    )
    registry = load_registry(root)
    assert (root / "../../outside").exists()
    issues = [i for i in registry.issues if "Evil" in i]
    assert issues, "an escaping path must be reported"
    # Order-independent: this project satisfies the placement rule via
    # category, but nothing here should depend on the escape issue being
    # first (or only) among Evil's issues.
    assert any("escape" in i.lower() for i in issues)


def test_every_issue_is_attributable_to_a_real_project(tmp_path):
    """Downstream marks the graph by testing each issue against each project
    name with `issue.startsWith(`${name}:`)` -- roadmap.js's `flagged` set and
    its per-node tooltip, and categories.js's entry-warn, all use that one
    test. Every issue this module builds must therefore begin with a real
    project's name followed by ":".

    Asserted as a prefix, not by splitting on the first ":": splitting is the
    contract the frontend abandoned, and it drops any project whose own name
    contains a colon. "Foo: Bar" here is exactly that case -- it is a legal
    registry name (conftest's colon_name_root serves one), and its issues
    split to "Foo", which is not a project. It carries a missing path, an
    unknown blocker and a cycle, so all three issue shapes are covered for it.
    """
    text = (
        '[[project]]\nname = "Foo: Bar"\npaths = ["nowhere"]\nblocked_by = ["Ghost", "B"]\n\n'
        '[[project]]\nname = "B"\npaths = ["research/0dte"]\nblocked_by = ["Foo: Bar"]\n'
    )
    registry = load_registry(write(tmp_path, text))
    assert registry.issues
    names = {p.name for p in registry.projects}
    for issue in registry.issues:
        assert any(issue.startswith(f"{name}:") for name in names), issue
    # The colon-named project is the point: without it every issue would also
    # satisfy the split contract and this test would prove nothing new.
    assert any(issue.startswith("Foo: Bar:") for issue in registry.issues), registry.issues


def test_a_project_blocking_itself_is_a_cycle(tmp_path):
    text = '[[project]]\nname = "A"\npaths = ["research/0dte"]\nblocked_by = ["A"]\n'
    registry = load_registry(write(tmp_path, text))
    assert any("cycle" in i.lower() for i in registry.issues)


def test_status_defaults_to_not_started(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n')
    registry = load_registry(tmp_path)
    assert registry.projects[0].status == "not-started"


def test_each_declared_status_survives_parsing(tmp_path):
    body = ""
    for i, status in enumerate(STATUSES):
        body += f'[[project]]\nname = "P{i}"\npaths = ["."]\ncategory = "x"\nstatus = "{status}"\n'
    write(tmp_path, body)
    registry = load_registry(tmp_path)
    assert [p.status for p in registry.projects] == list(STATUSES)


def test_an_unknown_status_is_an_issue_and_falls_back_to_not_started(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\nstatus = "finished"\n')
    registry = load_registry(tmp_path)
    # Falls back rather than raising: a typo must not remove the project.
    assert registry.projects[0].status == "not-started"
    assert any(i.startswith("A:") and "finished" in i for i in registry.issues)


def test_a_non_string_status_is_an_issue_not_a_crash(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\nstatus = 3\n')
    registry = load_registry(tmp_path)
    assert registry.projects[0].status == "not-started"
    assert any(i.startswith("A:") for i in registry.issues)


def test_a_project_with_neither_blocked_by_nor_category_is_an_issue(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\n')
    registry = load_registry(tmp_path)
    assert any(i.startswith("A:") and "category" in i for i in registry.issues)


def test_blocked_by_alone_satisfies_the_placement_rule(tmp_path):
    write(
        tmp_path,
        '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n'
        '[[project]]\nname = "B"\npaths = ["."]\nblocked_by = ["A"]\n',
    )
    registry = load_registry(tmp_path)
    assert not any(i.startswith("B:") for i in registry.issues)


def test_category_alone_satisfies_the_placement_rule(tmp_path):
    write(tmp_path, '[[project]]\nname = "A"\npaths = ["."]\ncategory = "x"\n')
    registry = load_registry(tmp_path)
    assert not any(i.startswith("A:") for i in registry.issues)


def test_the_registry_can_be_read_from_a_file_outside_the_root(tmp_path):
    root = tmp_path / "served"
    root.mkdir()
    (root / "docs").mkdir()
    elsewhere = tmp_path / "store" / "registry.toml"
    elsewhere.parent.mkdir()
    elsewhere.write_text(
        '[[project]]\nname = "A"\npaths = ["docs"]\ncategory = "x"\n', encoding="utf-8"
    )
    registry = load_registry(root, elsewhere)
    # paths still resolve against root, not against the registry's own folder.
    assert registry.projects[0].paths == ("docs",)
    assert registry.issues == []


def test_a_missing_registry_file_outside_the_root_is_no_registry(tmp_path):
    assert load_registry(tmp_path, tmp_path / "nope" / "registry.toml") is None
