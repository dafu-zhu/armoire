"""Tree, filter and routing, exercised in a real browser."""

from conftest import folder_snapshot


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
    """Checks the promise (the title) and the behaviour it describes (a
    double click actually does nothing) together: the two currently derive
    from the same `hasRegistry` value and cannot drift, but a regression that
    broke only the dblclick guard while leaving the tooltip ternary intact
    would still pass a title-only check.

    An end-state-only check (hash == "#/browse/", #roadmap hidden) is not
    enough on its own: on a folder with no registry, showRoadmap's own
    `registry === false` fallback bounces `#/` straight back to `#/browse/`
    and hides #roadmap too, so a dblclick handler that wrongly navigates to
    `#/` converges on exactly the same end state 400ms later -- the bounce
    just adds a flicker and two extra history entries nothing here checks.
    Recording every hash the page actually visits, via a hashchange listener
    installed before the gesture, catches that: a correctly-guarded dblclick
    never writes `#/` at all, so it can never appear in the recording, no
    matter what happens afterwards.
    """
    page.goto(f"{bare_server}/#/browse/")
    page.wait_for_selector("#breadcrumb [data-root]")
    crumb = page.locator("#breadcrumb [data-root]")
    assert "no roadmap" in (crumb.get_attribute("title") or "").lower()
    page.evaluate(
        "() => { "
        "window.__hashes = []; "
        "window.addEventListener('hashchange', () => window.__hashes.push(location.hash)); "
        "}"
    )
    crumb.dblclick()
    # Nothing to wait_for_selector on for "stayed put" -- give the click
    # half's deferred timer (see the leak-guard test below) a window to have
    # fired wrongly before checking nothing moved.
    page.wait_for_timeout(400)
    assert page.evaluate("location.hash") == "#/browse/"
    assert page.locator("#roadmap").is_hidden()
    assert "#/" not in page.evaluate("window.__hashes")


def test_a_pending_single_click_does_not_leak_into_a_later_roadmap_visit(live_server, page):
    """A click on the root crumb defers its own navigation by
    ROOT_CLICK_DELAY (app.js) so a following dblclick can still cancel it.
    If the roadmap is reached by some route *other* than that dblclick before
    the timer fires -- browser Back onto a prior roadmap entry, for instance
    -- the stale timer must not survive to fire later and drag the user back
    off the page they just reached."""
    page.goto(f"{live_server}/#/browse/notes")
    page.wait_for_selector("#breadcrumb [data-root]")
    page.locator("#breadcrumb [data-root]").click()
    # Reach the roadmap by a route other than the crumb's own dblclick,
    # before the deferred single-click timer (250ms) would fire.
    page.evaluate("() => { window.location.hash = '/'; }")
    page.wait_for_selector(".node")
    # Give the stale timer, if any survived, a window to fire wrongly.
    page.wait_for_timeout(400)
    assert page.evaluate("location.hash") == "#/"
    assert page.locator("#roadmap").is_visible()


def test_the_tree_has_no_horizontal_scrollbar(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    overflow = page.locator("#tree").evaluate("el => getComputedStyle(el).overflowX")
    assert overflow == "hidden"


def test_a_long_name_truncates_rather_than_widening_the_tree(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    assert page.locator("#tree").evaluate("el => el.scrollWidth <= el.clientWidth + 1")


SCROLLBAR_DISPLAY = "el => getComputedStyle(el, '::-webkit-scrollbar').display"


def test_the_tree_hides_its_scrollbar_but_no_other_pane_does(live_server, page):
    """The tree's right edge already carries a line -- the divider -- and a
    scrollbar arriving immediately beside it reads as one thick smudged
    border rather than as two separate controls.

    Asks the pseudo-element what it computes to rather than measuring
    offsetWidth - clientWidth, which would be the direct test of "takes no
    width" and cannot work here: headless Chromium draws overlay scrollbars,
    so that difference is already 1 (the border alone) whether the bar is
    hidden or not, and the measurement passes just as happily against no fix
    at all.

    #main is asserted alongside it because the rule this checks lives one
    line away from the global ::-webkit-scrollbar block that styles every
    other pane. Hiding the tree's bar by widening the blast radius of that
    block would satisfy a #tree-only assertion perfectly.

    A short viewport, so the pane genuinely overflows: at the default 720px
    the sample folder's root fits without scrolling at all.
    """
    page.set_viewport_size({"width": 1000, "height": 300})
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    tree = page.locator("#tree")
    assert tree.evaluate("el => el.scrollHeight > el.clientHeight")
    assert tree.evaluate(SCROLLBAR_DISPLAY) == "none"
    assert page.locator("#main").evaluate(SCROLLBAR_DISPLAY) != "none"


def test_the_tree_still_scrolls_with_its_scrollbar_hidden(live_server, page):
    """Hidden, not disabled. The wheel, the keyboard and revealPath's own
    scrollIntoView all still have to reach the bottom of a long tree."""
    page.set_viewport_size({"width": 1000, "height": 300})
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree .row")
    tree = page.locator("#tree")
    tree.evaluate("el => el.scrollTo(0, 200)")
    assert tree.evaluate("el => el.scrollTop") > 0


def test_dragging_the_divider_widens_the_tree(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    before = page.locator("#tree").bounding_box()["width"]
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] > before + 50


def test_the_divider_refuses_to_go_below_its_minimum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(0, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] >= 180


def test_the_divider_refuses_to_go_above_its_maximum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(2000, box["y"] + 100, steps=10)
    page.mouse.up()
    assert page.locator("#tree").bounding_box()["width"] <= 600


def test_the_divider_width_survives_a_reload(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    width = page.locator("#tree").bounding_box()["width"]
    page.reload()
    page.wait_for_selector("#divider")
    assert abs(page.locator("#tree").bounding_box()["width"] - width) < 2


def test_the_arrow_keys_move_the_divider(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    before = page.locator("#tree").bounding_box()["width"]
    page.locator("#divider").focus()
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    assert page.locator("#tree").bounding_box()["width"] > before


def test_dragging_the_divider_does_not_write_to_the_served_folder(live_server, page, sample_root):
    before = folder_snapshot(sample_root)
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    assert folder_snapshot(sample_root) == before


def test_the_home_key_jumps_the_divider_to_its_minimum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    page.locator("#divider").focus()
    page.keyboard.press("Home")
    assert abs(page.locator("#tree").bounding_box()["width"] - 180) <= 2


def test_the_end_key_jumps_the_divider_to_its_maximum(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    page.locator("#divider").focus()
    page.keyboard.press("End")
    assert abs(page.locator("#tree").bounding_box()["width"] - 600) <= 2


def test_the_divider_reports_its_aria_attributes(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    divider = page.locator("#divider")
    assert divider.get_attribute("role") == "separator"
    assert divider.get_attribute("aria-orientation") == "vertical"
    assert divider.get_attribute("aria-valuemin") == "180"
    assert divider.get_attribute("aria-valuemax") == "600"


def test_aria_valuenow_tracks_the_width_after_a_drag(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    box = page.locator("#divider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 100, steps=10)
    page.mouse.up()
    width = page.locator("#tree").bounding_box()["width"]
    valuenow = int(page.locator("#divider").get_attribute("aria-valuenow"))
    assert abs(valuenow - width) <= 2


def test_aria_valuenow_tracks_the_width_after_a_keyboard_move(live_server, page):
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#divider")
    page.locator("#divider").focus()
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    width = page.locator("#tree").bounding_box()["width"]
    valuenow = int(page.locator("#divider").get_attribute("aria-valuenow"))
    assert abs(valuenow - width) <= 2
