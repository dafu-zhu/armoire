"""Tree, filter and routing, exercised in a real browser."""


def test_tree_lists_the_root_folder(page, live_server):
    # A registry exists in the fixture, so "#/" is now the roadmap; the tree
    # only renders (and is only visible) under the browse route.
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    names = page.locator("#tree .row").all_inner_texts()
    assert any("notes" in name for name in names)
    assert any("README.md" in name for name in names)


def test_tree_hides_ignored_directories(page, live_server):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    assert all(".venv" not in name for name in page.locator("#tree .row").all_inner_texts())


def test_expanding_a_directory_reveals_its_children(page, live_server):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    assert page.locator('#tree [data-path="notes/deep"]').count() == 0
    page.locator('#tree [data-path="notes"]').click()
    page.wait_for_selector('#tree [data-path="notes/deep"]')
    assert page.locator('#tree [data-path="notes/deep"]').count() == 1


def test_clicking_a_file_updates_the_url(page, live_server):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    page.locator('#tree [data-path="code.py"]').click()
    page.wait_for_function("() => location.hash === '#/browse/code.py'", timeout=5000)
    assert page.evaluate("location.hash") == "#/browse/code.py"


def test_filter_finds_a_deeply_nested_file(page, live_server):
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    assert "notes/deep/buried.md" in page.locator("#filter-results li").first.inner_text()


def test_filter_ranks_tighter_matches_first(page, live_server):
    """Pins the ranking, not just membership: several fixture paths match "de".
    "code.py" ties "browse/inside.md" for tightest match on this query (both
    put "d" immediately before "e"), so this checks code.py ranks ahead of
    the much looser "buried.md" rather than assuming it is uniquely first."""
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("de")
    page.wait_for_selector("#filter-results li")
    results = page.locator("#filter-results li").all_inner_texts()
    assert len(results) > 1, "need multiple matches or this proves nothing"
    code_index = next(i for i, r in enumerate(results) if "code.py" in r)
    buried_index = next(i for i, r in enumerate(results) if "buried.md" in r)
    assert code_index < buried_index


def test_filter_enter_navigates_to_the_match(page, live_server):
    page.goto(live_server)
    page.wait_for_function("() => document.querySelector('#filter').placeholder.includes('Filter')")
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    page.locator("#filter").press("Enter")
    page.wait_for_function("() => location.hash === '#/browse/notes/deep/buried.md'", timeout=5000)
    assert page.evaluate("location.hash") == "#/browse/notes/deep/buried.md"


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


def test_filter_becomes_usable_once_indexing_finishes_even_if_it_was_not_ready_on_load(
    page, live_server
):
    """/api/index answers immediately with {"ready": false, "paths": []}
    while the background walk runs -- 3+ seconds on a large folder. The
    fixture's own index is already built before live_server starts
    (conftest.py calls index.wait() first), so ready:false is otherwise
    unreachable in this suite: reproduce it by answering not-ready on the
    first poll only, then letting every later poll through to the real,
    by-then-ready handler."""
    calls = {"n": 0}

    def handle(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ready": false, "paths": []}',
            )
        else:
            route.continue_()

    page.route("**/api/index", handle)
    page.goto(live_server)
    page.wait_for_function(
        "() => document.querySelector('#filter').placeholder.startsWith('Indexing')"
    )
    page.wait_for_function(
        "() => document.querySelector('#filter').placeholder.startsWith('Filter')",
        timeout=5000,
    )
    page.locator("#filter").fill("buried")
    page.wait_for_selector("#filter-results li")
    assert "notes/deep/buried.md" in page.locator("#filter-results li").first.inner_text()


def test_navigating_to_a_percent_named_file_renders_rather_than_hangs(page, live_server):
    """navigate() must encode each hash segment: a raw, unencoded "%" is not
    a valid percent-escape, and currentRoute()'s decodeURIComponent would
    throw on it. The root's own README already renders a .markdown-body on
    load, so this waits for its *content* to change rather than for the
    selector to merely exist -- otherwise the wait would pass immediately
    against the stale element and never observe the navigation at all."""
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    page.locator('#tree [data-path="50% off.md"]').click()
    page.wait_for_function(
        "() => document.querySelector('.markdown-body')?.innerText.includes('Percent')",
        timeout=5000,
    )
    assert page.locator("#content .error").count() == 0


def test_malformed_hash_surfaces_an_error_instead_of_freezing(page, live_server):
    """A hand-edited hash with a bare "%" (not a valid percent-escape) must
    not freeze the page: the hashchange listener is not inside a promise
    chain, so an uncaught decodeURIComponent throw there has no error card
    and nothing else in the console shows for it either."""
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    page.evaluate("() => { window.location.hash = '/browse/50%zz.md'; }")
    page.wait_for_selector("#content .error", timeout=5000)


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
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector('#tree [data-path="notes/deep/buried.md"]')
    assert page.locator('#tree [data-path="notes/deep/buried.md"]').count() == 1


def test_breadcrumb_reflects_the_current_path(page, live_server):
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector("#breadcrumb a")
    text = page.locator("#breadcrumb").inner_text()
    assert "notes" in text and "deep" in text and "buried.md" in text


def test_breadcrumb_links_point_into_the_browse_route(page, live_server):
    """inner_text alone cannot catch a breadcrumb whose href never migrated."""
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector("#breadcrumb a")
    hrefs = page.eval_on_selector_all(
        "#breadcrumb a", "els => els.map(e => e.getAttribute('href'))"
    )
    assert hrefs, "no breadcrumb links rendered"
    assert all(h.startswith("#/browse/") for h in hrefs), hrefs


def test_clicking_a_breadcrumb_link_navigates(page, live_server):
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector("#breadcrumb a")
    page.locator("#breadcrumb a", has_text="notes").first.click()
    page.wait_for_selector(".listing", timeout=5000)
    assert page.evaluate("location.hash").startswith("#/browse/notes")


def test_no_console_errors_during_navigation(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/#/browse/notes/deep/buried.md")
    page.wait_for_selector("#content")
    page.wait_for_load_state("networkidle")
    assert errors == []


def test_files_live_under_the_browse_prefix(page, live_server):
    page.goto(f"{live_server}/#/browse/code.py")
    page.wait_for_selector("pre.code", timeout=10000)
    assert "return" in page.locator("pre.code").inner_text()


def test_clicking_a_file_in_the_tree_writes_a_browse_url(page, live_server):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    page.locator('#tree [data-path="code.py"]').click()
    page.wait_for_function("() => location.hash === '#/browse/code.py'", timeout=5000)
    assert page.evaluate("location.hash") == "#/browse/code.py"


def test_a_relative_markdown_link_writes_a_browse_url(page, live_server):
    page.goto(f"{live_server}/#/browse/links.md")
    page.wait_for_selector(".markdown-body a", timeout=10000)
    href = page.locator(".markdown-body a").first.get_attribute("href")
    assert href.startswith("#/browse/")


def test_a_listing_link_writes_a_browse_url(page, live_server):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector(".listing a", timeout=10000)
    href = page.locator(".listing a").first.get_attribute("href")
    assert href.startswith("#/browse/")


def test_a_folder_named_browse_does_not_collide(page, live_server):
    page.goto(f"{live_server}/#/browse/browse/inside.md")
    page.wait_for_selector(".markdown-body h1", timeout=10000)
    assert page.locator(".markdown-body h1").inner_text() == "Inside a folder named browse"


def test_a_stale_phase_one_url_migrates_to_the_browse_route(page, live_server):
    """Bookmarks made before the prefix existed must keep working."""
    page.goto(f"{live_server}/#/code.py")
    page.wait_for_selector("pre.code", timeout=10000)
    assert page.evaluate("location.hash") == "#/browse/code.py"
    assert "return" in page.locator("pre.code").inner_text()


def test_a_stale_nested_url_migrates(page, live_server):
    page.goto(f"{live_server}/#/notes/deep/buried.md")
    page.wait_for_selector(".markdown-body h1", timeout=10000)
    assert page.evaluate("location.hash") == "#/browse/notes/deep/buried.md"


def test_the_breadcrumb_root_shows_the_served_path(live_server, page, sample_root):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    shown = page.locator("#breadcrumb [data-root]").inner_text()
    assert shown == str(sample_root).replace("\\", "/")


def test_the_root_crumb_is_one_element_not_a_trail(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    assert page.locator("#breadcrumb [data-root]").count() == 1


def test_clicking_the_root_crumb_goes_to_the_root_listing(live_server, page):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector("#breadcrumb [data-root]")
    page.locator("#breadcrumb [data-root]").click()
    page.wait_for_url("**/#/browse/")


def test_double_clicking_the_root_crumb_returns_to_the_roadmap(live_server, page):
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector("#breadcrumb [data-root]")
    page.locator("#breadcrumb [data-root]").dblclick()
    page.wait_for_selector(".node")
    assert page.locator("#roadmap").is_visible()


def test_a_folder_with_no_registry_says_the_gesture_is_inert(bare_server, page):
    page.goto(f"{bare_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    crumb = page.locator("#breadcrumb [data-root]")
    assert "no roadmap" in (crumb.get_attribute("title") or "").lower()
