"""The roadmap, exercised in a real browser."""

import time


def open_roadmap(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)


def test_roadmap_is_the_entry_screen_when_a_registry_exists(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap").is_visible()


def test_every_declared_project_becomes_a_node(page, live_server):
    open_roadmap(page, live_server)
    # .all_inner_texts() requires an HTMLElement (Playwright's innerText check
    # rejects any node outside the HTML namespace) and .node here is an SVG
    # <g>; .all_text_contents() works across namespaces. Visibility is
    # already established by open_roadmap()'s wait_for_selector above.
    labels = page.locator("#roadmap .node").all_text_contents()
    assert any("Downstream" in text for text in labels)
    assert any("Upstream" in text for text in labels)


def test_blocked_by_becomes_an_edge(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap .edge").count() == 1


def test_the_blocker_is_laid_out_before_the_blocked(page, live_server):
    """rankdir LR: a blocker must sit to the left of what it blocks."""
    open_roadmap(page, live_server)
    boxes = {}
    for handle in page.locator("#roadmap .node").element_handles():
        # .inner_text() requires an HTMLElement; .node is an SVG <g>, so use
        # .text_content(), which works on any node regardless of namespace.
        name = handle.text_content()
        boxes["Upstream" if "Upstream" in name else "Downstream"] = handle.bounding_box()["x"]
    assert boxes["Upstream"] < boxes["Downstream"]


def test_a_node_shows_its_commit_badge(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#roadmap .node-badge").count() >= 1


def test_a_due_date_appears_on_its_node(page, live_server):
    open_roadmap(page, live_server)
    assert "2026-08-17" in page.locator("#roadmap").inner_text()


def test_clicking_a_node_opens_the_project_route(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#roadmap .node", has_text="Upstream").first.click()
    page.wait_for_function("() => location.hash.startsWith('#/project/')", timeout=5000)
    assert page.evaluate("location.hash") == "#/project/Upstream"


def test_a_folder_with_no_registry_opens_on_the_file_browser(page, bare_server):
    """The state every folder is in until someone writes an armoire.toml."""
    page.goto(bare_server)
    page.wait_for_selector(".listing", timeout=15000)
    assert page.locator(".listing").count() == 1
    assert page.locator("#roadmap").is_hidden()
    assert page.evaluate("location.hash") == "#/browse/"


def test_no_console_errors_rendering_the_roadmap(page, live_server):
    errors = []
    page.on(
        "console",
        lambda m: errors.append((m.text, m.location.get("url", ""))) if m.type == "error" else None,
    )
    page.on("pageerror", lambda e: errors.append((str(e), "")))
    open_roadmap(page, live_server)
    page.wait_for_load_state("networkidle")
    assert errors == []


def test_the_file_browser_is_not_shown_while_the_roadmap_loads(page, live_server):
    """/api/projects walks git and can take seconds; showing the tree meanwhile
    reads as opening on the wrong screen."""
    page.route("**/api/projects", lambda route: (time.sleep(0.6), route.continue_())[-1])
    page.goto(live_server)
    page.wait_for_timeout(250)
    assert page.locator("#tree").is_hidden()
    assert page.locator("#roadmap").is_visible()
    page.wait_for_selector("#roadmap .node", timeout=15000)


def test_a_failed_projects_fetch_shows_an_error_not_a_blank_screen(page, live_server):
    """Committing to the roadmap before the fetch must not leave a blank
    screen if the fetch itself fails outright."""
    page.route("**/api/projects", lambda route: route.abort())
    page.goto(live_server)
    page.wait_for_selector("#roadmap .error", timeout=15000)
    assert page.locator("#roadmap").is_visible()


def test_an_empty_registry_says_so_instead_of_rendering_a_blank_canvas(page, empty_registry_server):
    """Zero [[project]] entries is valid TOML and reaches renderRoadmap."""
    page.goto(empty_registry_server)
    page.wait_for_selector("#roadmap .empty", timeout=15000)
    assert page.locator("#roadmap .empty").is_visible()
    assert page.locator("#roadmap .node").count() == 0


def test_the_viewbox_stays_finite_for_an_empty_graph(page, empty_registry_server):
    """app.js now never calls renderRoadmap with zero projects (it shows the
    empty-state message first), so the above test alone cannot reach
    roadmap.js's own fallback -- dagre leaves graph.width at -Infinity for an
    empty graph, which `|| 800` cannot catch because -Infinity is truthy.
    Call renderRoadmap directly, the way any other future caller could."""
    page.goto(empty_registry_server)
    page.wait_for_selector("#roadmap .empty", timeout=15000)
    view_box = page.evaluate(
        """async () => {
            const { renderRoadmap } = await import('/roadmap.js');
            const canvas = document.getElementById('roadmap-canvas');
            renderRoadmap(canvas, { projects: [], issues: [] }, () => {});
            return canvas.getAttribute('viewBox');
        }"""
    )
    assert view_box == "0 0 800 400"


def test_a_colon_in_a_project_name_does_not_drop_its_marker(page, colon_name_server):
    """flagged must match issues the same way the per-node tooltip does
    (issue.startsWith(`${name}:`)), or a name containing ":" loses its
    warning marker even though it has a real issue against it."""
    page.goto(colon_name_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#roadmap .node-warn").count() == 1
