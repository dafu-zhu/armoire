"""Tree, filter and routing, exercised in a real browser."""

import pytest


def test_tree_lists_the_root_folder(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    names = page.locator("#tree .row").all_inner_texts()
    assert any("notes" in name for name in names)
    assert any("README.md" in name for name in names)


def test_tree_hides_ignored_directories(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    assert all(".venv" not in name for name in page.locator("#tree .row").all_inner_texts())


def test_expanding_a_directory_reveals_its_children(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    assert page.locator('#tree [data-path="notes/deep"]').count() == 0
    page.locator('#tree [data-path="notes"]').click()
    page.wait_for_selector('#tree [data-path="notes/deep"]')
    assert page.locator('#tree [data-path="notes/deep"]').count() == 1


def test_clicking_a_file_updates_the_url(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    page.locator('#tree [data-path="code.py"]').click()
    page.wait_for_function("() => location.hash === '#/code.py'")


def test_filter_finds_a_deeply_nested_file(page, live_server):
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    assert "notes/deep/buried.md" in page.locator("#filter-results li").first.inner_text()


def test_filter_enter_navigates_to_the_match(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#tree .row")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    page.locator("#filter").press("Enter")
    page.wait_for_function("() => location.hash === '#/notes/deep/buried.md'")


def test_deep_link_reload_expands_the_tree_to_the_file(page, live_server):
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector('#tree [data-path="notes/deep/buried.md"]')
    assert page.locator('#tree [data-path="notes/deep/buried.md"]').count() == 1


def test_breadcrumb_reflects_the_current_path(page, live_server):
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector("#breadcrumb a")
    text = page.locator("#breadcrumb").inner_text()
    assert "notes" in text and "deep" in text and "buried.md" in text


@pytest.mark.xfail(reason="preview.js arrives in Task 11", strict=True)
def test_no_console_errors_during_navigation(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector("#content")
    page.wait_for_load_state("networkidle")
    assert errors == []
