"""Tree, filter and routing, exercised in a real browser."""


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
    page.wait_for_function("() => location.hash === '#/code.py'", timeout=5000)
    assert page.evaluate("location.hash") == "#/code.py"


def test_filter_finds_a_deeply_nested_file(page, live_server):
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    assert "notes/deep/buried.md" in page.locator("#filter-results li").first.inner_text()


def test_filter_ranks_tighter_matches_first(page, live_server):
    """Pins the ranking, not just membership: several fixture paths match "de"."""
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("de")
    page.wait_for_selector("#filter-results li")
    results = page.locator("#filter-results li").all_inner_texts()
    assert len(results) > 1, "need multiple matches or this proves nothing"
    assert "code.py" in results[0]
    assert any("buried.md" in r for r in results)
    assert results.index(next(r for r in results if "buried.md" in r)) > 0


def test_filter_enter_navigates_to_the_match(page, live_server):
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    page.locator("#filter").press("Enter")
    page.wait_for_function("() => location.hash === '#/notes/deep/buried.md'", timeout=5000)
    assert page.evaluate("location.hash") == "#/notes/deep/buried.md"


def test_filter_recovers_when_typing_before_the_index_is_ready(page, live_server):
    """The index can take seconds on a real folder; the fixture's own index
    is already built before the test server starts, so the race is
    reproduced by holding the /api/index response until after the user has
    already typed, then releasing it. (A blocking sleep() in the route
    handler does not work here: it stalls Playwright's whole dispatcher, so
    every other in-flight request -- including /api/tree and the page's own
    load event -- waits behind it too, and the index ends up populated
    before the fill() ever runs.)"""
    held = {}
    page.route("**/api/index", lambda route: held.__setitem__("route", route))

    page.goto(live_server)
    page.wait_for_selector("#filter")
    page.locator("#filter").fill("buried")  # typed while /api/index is still held back
    held["route"].continue_()

    page.wait_for_selector("#filter-results li", timeout=5000)
    assert "buried.md" in page.locator("#filter-results li").first.inner_text()


def test_filter_placeholder_reports_index_failure(page, live_server):
    """A backend error on /api/index must not leave the filter silently
    stuck on its initial placeholder forever, with only an unhandled
    rejection in the console to show for it."""
    page.route("**/api/index", lambda route: route.abort())
    page.goto(live_server)
    page.wait_for_function(
        "() => document.querySelector('#filter').placeholder === 'Filter unavailable'"
    )


def test_tree_failure_surfaces_an_error_instead_of_hanging(page, live_server):
    """A backend error on the initial directory listing must surface in the
    UI, not just as an unhandled promise rejection in the console."""
    page.route("**/api/tree*", lambda route: route.abort())
    page.goto(live_server)
    page.wait_for_selector("#content .error")


def test_deep_link_reload_expands_the_tree_to_the_file(page, live_server):
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector('#tree [data-path="notes/deep/buried.md"]')
    assert page.locator('#tree [data-path="notes/deep/buried.md"]').count() == 1


def test_breadcrumb_reflects_the_current_path(page, live_server):
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector("#breadcrumb a")
    text = page.locator("#breadcrumb").inner_text()
    assert "notes" in text and "deep" in text and "buried.md" in text


def test_no_console_errors_during_navigation(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector("#content")
    page.wait_for_load_state("networkidle")
    assert errors == []
