"""The roadmap, exercised in a real browser."""

import time

import pytest

from armoire.projects import STATUSES
from conftest import folder_snapshot

# The cycle order status.js's nextStatus walks. Imported from the server's own
# tuple rather than retyped: STATUSES and STATUS_ORDER (status.js) are the same
# five values in the same order, and the endpoint validates against STATUSES.
STATUS_ORDER = list(STATUSES)


def open_roadmap(page, live_server):
    page.goto(live_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)


def assert_inside_viewport(page, locator):
    """A message the user cannot read is not a message.

    `is_visible()` and wait_for_selector's default `visible` state only check
    for a non-empty box and no visibility:hidden -- neither looks at where the
    box actually sits. Appended to #roadmap as a normal-flow block, these boxes
    started at the bottom edge of the height:100% canvas: measured at y=689 in
    a 720px viewport, with 38 of their 69px past the fold and only 7px of the
    21px text row above it, on a page that had to grow a scrollbar to reach the
    rest.
    """
    box = locator.bounding_box()
    viewport = page.viewport_size
    assert box is not None, "no box at all"
    assert box["y"] >= 0, (box, viewport)
    assert box["y"] + box["height"] <= viewport["height"], (box, viewport)
    assert box["x"] >= 0, (box, viewport)
    assert box["x"] + box["width"] <= viewport["width"], (box, viewport)


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


def test_every_root_renders_at_the_same_leftmost_x(page, layout_server):
    """Every project nothing blocks must render hard left, not merely
    "before what it blocks".

    sample_root's single edge is too simple to prove this: with only one rank
    of depth, dagre's default 'network-simplex' ranker places its lone root
    at rank 0 regardless, so a bug that only shows up when a root's sole
    dependent sits several ranks away would pass unnoticed there.
    layout_server's registry (RootA -> MidA -> Leaf, RootB -> Leaf) gives
    RootB slack that network-simplex spends by sliding it one rank toward
    Leaf -- off the left edge RootA sits on, even though nothing blocks RootB
    either. roadmap.js's layout() closes that slack with a high-weight pin
    edge from every root to a shared (and later removed) anchor node, which
    forces every root to the same rank regardless of how far its own
    dependents reach.
    """
    page.goto(layout_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)
    boxes = {}
    for handle in page.locator("#roadmap .node").element_handles():
        name = handle.text_content()
        key = next(n for n in ("RootA", "RootB", "MidA", "Leaf") if n in name)
        boxes[key] = handle.bounding_box()["x"]
    assert abs(boxes["RootA"] - boxes["RootB"]) < 1, boxes
    # Sharing an x is the load-bearing claim, but on its own it is satisfied
    # by both roots drifting right together. Rank 0 is where they have to
    # land, so pin them against a node that is genuinely downstream.
    assert boxes["RootA"] < boxes["MidA"], boxes


def test_hovering_a_node_dims_dependency_unrelated_nodes(page, layout_server):
    """RootB shares Leaf with MidA but is not upstream or downstream of it."""
    page.goto(layout_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)

    page.locator('.node[data-name="MidA"]').hover()
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('.node[data-name=RootB]')).opacity)"
        " < 0.25"
    )

    opacity = page.locator("#roadmap .node").evaluate_all(
        "nodes => Object.fromEntries(nodes.map(node => "
        "[node.dataset.name, Number(getComputedStyle(node).opacity)]))"
    )
    assert opacity["RootB"] < 0.25, opacity
    assert opacity["RootA"] > 0.5, opacity
    assert opacity["MidA"] > 0.5, opacity
    assert opacity["Leaf"] > 0.5, opacity


def test_hovering_a_node_dims_edges_outside_its_dependency_path(page, layout_server):
    page.goto(layout_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)

    page.locator('.node[data-name="MidA"]').hover()
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('.node[data-name=RootB]')).opacity)"
        " < 0.25"
    )

    def edge_opacity(source, target):
        edge = page.locator(f'.edge[data-from="{source}"][data-to="{target}"]')
        assert edge.count() == 1, (source, target)
        return edge.evaluate("path => Number(getComputedStyle(path).opacity)")

    assert edge_opacity("RootA", "MidA") >= 0.5
    assert edge_opacity("MidA", "Leaf") >= 0.5
    assert edge_opacity("RootB", "Leaf") < 0.25


def test_leaving_a_hovered_node_restores_the_roadmap(page, layout_server):
    page.goto(layout_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)

    page.locator('.node[data-name="MidA"]').hover()
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('.node[data-name=RootB]')).opacity)"
        " < 0.25"
    )
    page.locator("#status").hover()
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('.node[data-name=RootB]')).opacity)"
        " > 0.5"
    )

    node_opacity = page.locator("#roadmap .node").evaluate_all(
        "nodes => nodes.map(node => Number(getComputedStyle(node).opacity))"
    )
    edge_opacity = page.locator("#roadmap .edge").evaluate_all(
        "edges => edges.map(edge => Number(getComputedStyle(edge).opacity))"
    )
    assert all(value > 0.5 for value in node_opacity), node_opacity
    assert all(value >= 0.5 for value in edge_opacity), edge_opacity


def test_a_dependency_cycle_does_not_truncate_the_hover_path(page, live_server):
    projects = [
        {
            "name": name,
            "paths": ["."],
            "blocked_by": blocked_by,
            "category": "course",
            "due": None,
            "note": None,
            "status": "active",
            "isolated": False,
            "is_habit": False,
            "habit_unlocked": False,
            "habit_locked_by": [],
        }
        for name, blocked_by in (
            ("A", ["B"]),
            ("B", ["A"]),
            ("C", ["B"]),
            ("X", []),
            ("Y", ["X"]),
        )
    ]
    page.route(
        "**/api/projects",
        lambda route: route.fulfill(
            json={
                "root": "cycle-fixture",
                "registry": True,
                "issues": ["A: dependency cycle via A -> B -> A"],
                "projects": projects,
            }
        ),
    )
    page.goto(live_server)
    page.wait_for_selector('.node[data-name="A"]', timeout=15000)

    page.locator('.node[data-name="A"]').hover()
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('.node[data-name=X]')).opacity)"
        " < 0.25"
    )

    assert (
        page.locator('.node[data-name="C"]').evaluate(
            "node => Number(getComputedStyle(node).opacity)"
        )
        > 0.5
    )


def test_a_due_date_appears_on_its_node(page, live_server):
    open_roadmap(page, live_server)
    assert "2026-08-17" in page.locator("#roadmap").inner_text()


def test_clicking_a_node_opens_the_side_panel(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#roadmap .node", has_text="Upstream").first.click()
    page.wait_for_selector("#project-panel:visible", timeout=5000)
    assert page.locator("#project-panel h2").inner_text() == "Upstream"
    # A single click previews in place; it never navigates away.
    assert page.evaluate("location.hash") in ("", "#/")


def test_double_clicking_a_node_opens_its_folder(page, live_server):
    open_roadmap(page, live_server)
    page.locator('#roadmap .node[data-name="Upstream"]').dblclick()
    page.wait_for_function("() => location.hash.startsWith('#/browse/')", timeout=5000)
    page.wait_for_selector(".listing", timeout=5000)
    assert page.locator("#project-panel").is_hidden()


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
    # #divider is a third sibling of #tree and #main in #body's flex row --
    # without pairing its `hidden` state to theirs it would render as an
    # orphan 5px bar next to the roadmap while #tree itself is hidden.
    assert page.locator("#divider").is_hidden()
    assert page.locator("#roadmap").is_visible()
    page.wait_for_selector("#roadmap .node", timeout=15000)


def test_a_failed_projects_fetch_shows_an_error_not_a_blank_screen(page, live_server):
    """Committing to the roadmap before the fetch must not leave a blank
    screen if the fetch itself fails outright."""
    page.route("**/api/projects", lambda route: route.abort())
    page.goto(live_server)
    page.wait_for_selector("#roadmap .error", timeout=15000)
    assert page.locator("#roadmap").is_visible()
    # "not a blank screen" is a claim about what the user sees, so it has to be
    # checked where the user is looking.
    assert_inside_viewport(page, page.locator("#roadmap .error"))


def test_an_empty_registry_falls_back_to_the_file_browser_on_every_visit(
    page, empty_registry_server
):
    """Zero [[project]] entries is valid TOML and reaches showRoadmap, but a
    stub registry is the normal state for a folder nobody has described yet --
    the same "no roadmap here" exit as no registry file at all, not a message
    rendered in the roadmap panel. Repeated visits must keep taking that exit
    rather than getting stuck, or leaving the roadmap panel visible, on a
    second pass."""
    page.goto(empty_registry_server)
    # empty_registry_server's served folder holds no files of its own, so the
    # browser renders ".empty" ("This folder is empty."), not ".listing" --
    # "#main:visible" is the one signal common to both.
    page.wait_for_selector("#main:visible", timeout=15000)
    assert page.locator("#roadmap").is_hidden()
    assert page.evaluate("location.hash") == "#/browse/"
    for _ in range(2):
        page.evaluate("window.location.hash = '/'")
        page.wait_for_function("() => location.hash === '#/browse/'")
        page.wait_for_selector("#main:visible", timeout=5000)
    assert page.locator("#roadmap").is_hidden()
    assert page.locator("#roadmap .node").count() == 0
    assert page.locator("#roadmap .empty").count() == 0


def test_a_stale_error_card_does_not_survive_a_successful_revisit(page, live_server):
    """One transient fetch failure used to leave its error card sitting
    underneath every graph rendered afterwards."""
    failed = {"once": False}

    def handler(route):
        if failed["once"]:
            route.continue_()
        else:
            failed["once"] = True
            route.abort()

    page.route("**/api/projects", handler)
    page.goto(live_server)
    page.wait_for_selector("#roadmap .error", timeout=15000)
    page.evaluate("window.location.hash = '/browse/'")
    page.wait_for_function("() => location.hash === '#/browse/'")
    page.evaluate("window.location.hash = '/'")
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#roadmap .error").count() == 0


def test_a_stale_category_column_does_not_survive_a_failed_revisit(page, live_server):
    """The mirror of test_a_stale_error_card_does_not_survive_a_successful_revisit
    above, but the other direction (a *successful* visit followed by a
    *failed* one), and scoped to #categories rather than the error card.

    showRoadmapMessage clears the canvas on every error exit (both the
    fetch's own catch and the data.error branch route through it), but
    nothing cleared #categories -- renderCategories is the only other writer
    of #categories, and neither error exit ever reaches it. A transient
    failure after a populated visit used to leave the column showing
    isolated projects from the *previous* successful load, sitting beside a
    card that says the fetch itself just failed.
    """
    open_roadmap(page, live_server)
    page.wait_for_selector("#categories .category")
    page.evaluate("window.location.hash = '/browse/'")
    page.wait_for_function("() => location.hash === '#/browse/'")
    page.route("**/api/projects", lambda route: route.abort())
    page.evaluate("window.location.hash = '/'")
    page.wait_for_selector("#roadmap .error", timeout=15000)
    assert page.locator("#categories .category").count() == 0


def test_a_throw_inside_render_shows_an_error_not_a_stuck_loading_status(page, live_server):
    """showRoadmap() was called unawaited and uncaught, so anything renderRoadmap
    threw left the screen on "Loading roadmap…" with no error card at all."""
    page.route(
        "**/vendor/dagre.js",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="window.dagre = { graphlib: { Graph: function () "
            "{ throw new Error('dagre is broken'); } } };",
        ),
    )
    page.goto(live_server)
    page.wait_for_selector("#roadmap .error", timeout=15000)
    assert "dagre is broken" in page.locator("#roadmap .error").inner_text()
    assert_inside_viewport(page, page.locator("#roadmap .error"))


def test_the_viewbox_stays_finite_for_an_empty_graph(page, empty_registry_server):
    """app.js now never calls renderRoadmap with zero projects (it falls back
    to the file browser instead), so no other test reaches roadmap.js's own
    fallback -- dagre leaves graph.width at -Infinity for an empty graph,
    which `|| 800` cannot catch because -Infinity is truthy.
    Call renderRoadmap directly, the way any other future caller could."""
    page.goto(empty_registry_server)
    # empty_registry_server's served folder holds no files of its own, so the
    # browser renders ".empty" ("This folder is empty."), not ".listing".
    page.wait_for_selector("#main:visible", timeout=15000)
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
    warning marker even though it has a real issue against it.

    Scoped to "Foo: Bar"'s own node, not a bare count over the whole graph:
    colon_name_root now declares a second project ("Dependent", added so
    "Foo: Bar" stays connected under task 9's isolation filter) that carries
    no issue of its own. An unscoped count == 1 would still pass if a
    regression flagged "Dependent" instead of "Foo: Bar" -- the count would
    be right for the wrong reason."""
    page.goto(colon_name_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator('#roadmap .node[data-name="Foo: Bar"] .node-warn').count() == 1


def drag_node(page, name, dx, dy):
    node = page.locator(f'#roadmap .node[data-name="{name}"]')
    box = node.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy, steps=8)
    page.mouse.up()
    return box


def test_dragging_moves_a_node(page, live_server):
    open_roadmap(page, live_server)
    before = drag_node(page, "Upstream", 120, 60)
    after = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(after["x"] - before["x"] - 120) < 8
    assert abs(after["y"] - before["y"] - 60) < 8


def test_a_dragged_position_survives_a_reload(page, live_server):
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 120, 60)
    moved = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    page.reload()
    page.wait_for_selector("#roadmap .node", timeout=15000)
    restored = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(restored["x"] - moved["x"]) < 4


def test_reset_restores_the_computed_layout(page, live_server):
    open_roadmap(page, live_server)
    original = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    drag_node(page, "Upstream", 120, 60)
    page.locator("#layout-reset").click()
    page.wait_for_timeout(300)
    restored = page.locator('#roadmap .node[data-name="Upstream"]').bounding_box()
    assert abs(restored["x"] - original["x"]) < 4


def test_dragging_does_not_write_to_the_served_folder(page, live_server, sample_root):
    """localStorage, not disk -- the read-only guarantee covers the roadmap too."""
    before = folder_snapshot(sample_root)
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 90, 40)
    page.wait_for_timeout(300)
    assert folder_snapshot(sample_root) == before


def test_zoom_controls_change_the_reported_level(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#zoom-in").click()
    assert page.locator("#zoom-level").inner_text() != "100%"


def test_dragging_a_node_does_not_open_its_project(page, live_server):
    """The whole point of suppressClick: a reposition must not navigate away,
    and must not open the side panel either -- a drag's pointerup still
    dispatches a native click, which suppressClick must swallow before it
    ever reaches the click-open scheduling."""
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 120, 60)
    page.wait_for_timeout(400)
    assert page.evaluate("location.hash") in ("", "#/")
    assert page.locator("#roadmap .node").first.is_visible()
    assert page.locator("#project-panel").is_hidden()


def test_clicking_a_node_without_dragging_still_opens_the_panel(page, live_server):
    """suppressClick must not suppress a genuine click."""
    open_roadmap(page, live_server)
    page.locator('#roadmap .node[data-name="Upstream"]').click()
    page.wait_for_selector("#project-panel:visible", timeout=5000)
    assert page.locator("#project-panel h2").inner_text() == "Upstream"


def test_a_corrupt_null_layout_entry_does_not_take_the_roadmap_down(page, live_server):
    """JSON.parse('null') succeeds and yields null; Object.entries(null) throws
    unless loadSaved guards against it -- and an uncaught throw inside
    renderRoadmap would leave the roadmap with no nodes at all."""
    import json

    root = page.request.get(f"{live_server}/api/projects").json()["root"]
    key = f"armoire:layout:{root}"
    page.add_init_script(f"window.localStorage.setItem({json.dumps(key)}, 'null')")
    open_roadmap(page, live_server)
    assert page.locator("#roadmap .node").count() >= 1


def test_revisiting_the_roadmap_does_not_accumulate_listeners(page, live_server):
    """Each visit re-runs renderRoadmap against the same persistent
    #roadmap-canvas element. Without aborting the previous run's listeners
    they pile up for the lifetime of the page -- but a behavioural check on
    the canvas's final state cannot catch it: every surviving duplicate
    listener holds its own independent `positions`/`dragging` closure that
    starts at the same value and evolves in lockstep with all the others on
    every real event, so the rendered result is coincidentally correct no
    matter how many copies are attached. The actual, catchable symptom is
    duplicated *work*: each surviving listener independently calls its own
    write to localStorage, so after N revisits a single canvas drag writes
    the layout key N+1 times instead of once. Spying on
    Storage.prototype.setItem counts this directly instead of guessing at an
    observable side effect.

    (This test used to also click #rail-toggle and assert its own write
    count, closing the same gap for rail.js's toggle listener -- task 9
    deleted the rail along with that listener, so only the canvas half
    remains.)

    AbortController is wrapped only to count constructions, giving the test
    a way to wait for proof that a given revisit's abort()+render()+attach()
    block has actually run, rather than guessing at a timeout. An earlier
    version of this test gated each iteration on
    page.wait_for_load_state("networkidle") alone and flaked at the end of
    the full file: networkidle tracks network sockets, not whether the JS
    continuation scheduled after the response body arrives has actually been
    run, and under a loaded machine that gap was observed to widen past
    400ms, wide enough to occasionally start the drag against a still-stale
    render."""
    page.add_init_script(
        """
        window.__acCreates = 0;
        const OriginalAbortController = window.AbortController;
        window.AbortController = class extends OriginalAbortController {
            constructor() {
                super();
                window.__acCreates += 1;
            }
        };
        """
    )
    open_roadmap(page, live_server)
    for i in range(3):
        page.evaluate("window.location.hash = '/browse/'")
        page.wait_for_function("() => location.hash === '#/browse/'")
        page.evaluate("window.location.hash = '/'")
        page.wait_for_selector("#roadmap .node[data-name='Upstream']", timeout=15000)
        # One showRoadmap() call makes exactly one AbortController: the
        # initial open_roadmap() plus this being the (i+1)th revisit.
        page.wait_for_function(f"() => window.__acCreates === {i + 2}", timeout=15000)

    page.evaluate(
        """() => {
            window.__writes = { layout: 0 };
            const original = Storage.prototype.setItem;
            Storage.prototype.setItem = function (key, value) {
                if (key.startsWith('armoire:layout:')) window.__writes.layout += 1;
                return original.call(this, key, value);
            };
        }"""
    )

    drag_node(page, "Upstream", 80, 30)
    page.wait_for_timeout(300)
    layout_writes = page.evaluate("window.__writes.layout")
    assert layout_writes == 1, layout_writes


def test_an_unknown_project_shows_an_error_not_a_blank_page(page, live_server):
    page.goto(f"{live_server}/#/project/Ghost")
    page.wait_for_selector("#content .error", timeout=10000)
    assert page.locator("#content .error").inner_text().strip() != ""


def test_a_long_note_stays_inside_its_node(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    for name in page.locator(".node").evaluate_all("nodes => nodes.map(n => n.dataset.name)"):
        node = page.locator(f'.node[data-name="{name}"]')
        rect = node.locator("rect").bounding_box()
        for i in range(node.locator("text").count()):
            text = node.locator("text").nth(i).bounding_box()
            if text is None:
                continue
            assert text["x"] >= rect["x"] - 1, name
            assert text["x"] + text["width"] <= rect["x"] + rect["width"] + 1, name
            assert text["y"] + text["height"] <= rect["y"] + rect["height"] + 1, name


def test_a_long_note_wraps_onto_several_lines(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    # Scoped to the one node with the long note. Counting tspans across every
    # node would pass with two nodes of one line each, which proves nothing
    # about wrapping.
    lines = page.locator('.node[data-name="Downstream"] .node-sub tspan').count()
    assert lines >= 2, lines


def test_nodes_no_longer_show_a_commit_count(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator(".node .node-badge").count() == 0


def test_the_wrap_probe_measures_at_the_rendered_subtitles_font_size(live_server, page):
    """wrapLines() measures every candidate line against a probe <text>
    standing in for the real .node-sub -- if the probe is styled differently
    (font-size, in particular), every wrap decision, and therefore every
    node height, is computed against the wrong width.

    Regression this guards: a probe appended directly to the canvas, with no
    `.node` ancestor, missed `.node .node-sub { font-size: 11px }` (a
    descendant selector) entirely and silently measured at the body's 14px
    instead. That was safe only by coincidence -- 14 > 11 means the probe
    always over-measures and wraps early, never late -- so no containment or
    line-count test caught it. If the two font-sizes ever swapped which was
    larger, this would flip from "wastes space" to "overflows the box" with
    nothing to catch it. This spies on
    SVGTextElement.prototype.getComputedTextLength to capture the font-size
    actually in effect at every measurement call, and asserts it always
    matches the font-size a real rendered .node .node-sub uses, rather than
    asserting a specific number in either place -- a future edit to the
    shared CSS rule moves both together and keeps passing; only a probe that
    stops reading that rule at all would fail it.
    """
    page.add_init_script(
        """
        window.__probeFontSizes = [];
        const original = SVGTextElement.prototype.getComputedTextLength;
        SVGTextElement.prototype.getComputedTextLength = function () {
            window.__probeFontSizes.push(getComputedStyle(this).fontSize);
            return original.call(this);
        };
        """
    )
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    probe_sizes = set(page.evaluate("window.__probeFontSizes"))
    rendered_size = page.locator('.node[data-name="Downstream"] .node-sub').evaluate(
        "el => getComputedStyle(el).fontSize"
    )
    assert probe_sizes, "expected wrapLines to measure at least one candidate"
    assert probe_sizes == {rendered_size}, (probe_sizes, rendered_size)


def _status_reset_fixture(name):
    """Build a fixture that restores `name`'s server-side status after a test
    that changes it.

    live_server and sample_root are both session-scoped (conftest.py), so a
    status PUT from one test is visible to every test that runs afterward in
    this file: state.json is keyed by sample_root's own path and lives on
    disk under the session-scoped store, independent of which live_server
    request happened to write it.

    A dedicated function-scoped *server* fixture would not actually fix this
    -- store.write_state(root, state) is keyed by `root`, not by server/app
    instance, so a fresh app pointed at the same sample_root would read and
    write the exact same state.json a previous server already wrote to. Only
    a fresh *root* (its own folder plus its own registry) would truly
    isolate the write, and building one per test would either duplicate
    sample_root's Upstream/Downstream/blocked_by arrangement or cost an
    index-wait plus a new server thread on every one of these tests, for a
    fixture the ~30 other tests in this file already share for free.

    Restoring in a fixture teardown instead -- functionally a `finally`
    block, shared here rather than pasted into every mutating test -- reads
    `name`'s actual pre-test status from the server itself, rather than
    assuming the registry's default ("not-started"), so the restore is correct
    even if a test runs alone, out of order, or a prior run in this session
    already left `name` on some other status.

    A factory, not two copies of the same fixture body, because Important 3
    (Task 7 fix round 1) needs the same restore for Downstream, not just
    Upstream.
    """

    @pytest.fixture
    def _reset(live_server, page):
        before = page.request.get(f"{live_server}/api/projects").json()
        original = next(p["status"] for p in before["projects"] if p["name"] == name)
        yield
        response = page.request.put(
            f"{live_server}/api/status",
            headers={"X-Armoire": "1"},
            data={"name": name, "status": original},
        )
        # Unchecked, a future guard change to /api/status (a stricter host
        # check, a renamed header) could make this restore a silent no-op --
        # the next test to touch this project would then inherit whatever
        # status this test left it on, and the resulting failure would point
        # nowhere near the real cause.
        assert response.ok, (response.status, name, original)

    return _reset


reset_upstream_status = _status_reset_fixture("Upstream")
reset_downstream_status = _status_reset_fixture("Downstream")
reset_standalone_status = _status_reset_fixture("Standalone")


def test_the_four_statuses_render_four_distinct_borders(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    seen = set()
    for status in ["not-started", "active", "paused", "done"]:
        page.evaluate(
            "s => document.querySelector('.node').setAttribute('class', 'node cat-0 status-' + s)",
            status,
        )
        seen.add(
            page.locator(".node rect").first.evaluate(
                "r => getComputedStyle(r).strokeWidth + '|' + getComputedStyle(r).strokeDasharray"
            )
        )
    assert len(seen) == 4, seen


def test_status_chips_render_four_distinct_colours(live_server, page):
    """The shape glyphs (○ ● ◐ ✓) alone are hard to tell apart at the chip's
    12px size; colour is the second, independent channel app.css adds on top
    of them."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    seen = set()
    for status in ["not-started", "active", "paused", "done"]:
        page.evaluate(
            "s => document.querySelector('.node').setAttribute('class', 'node cat-0 status-' + s)",
            status,
        )
        seen.add(page.locator(".node .status-chip").first.evaluate("c => getComputedStyle(c).fill"))
    assert len(seen) == 4, seen


def test_the_node_title_is_larger_than_its_subtitle(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    # Downstream carries both a due date and a note, so it has a .node-sub to
    # compare against.
    node = page.locator('.node[data-name="Downstream"]')
    title_size = node.locator(".node-title").evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)"
    )
    sub_size = node.locator(".node-sub").first.evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)"
    )
    assert title_size > sub_size, (title_size, sub_size)


def test_blocked_and_ready_render_different_fills_on_an_uncategorised_node(live_server, page):
    """categoryClass() returns 'cat-5' (fill: var(--subtle)) for any project
    with no category, and blocked_by with no category is an explicitly
    supported registry shape (tests/test_projects.py:234). .node.blocked
    rect used to fill with that same var(--subtle) -- since the border
    encodes status only, a blocked, uncategorised node and a ready,
    uncategorised node computed to the exact same fill, so the "waiting"
    signal carried zero bits for that whole category. Scoped to a single
    node's rect the same way test_the_four_statuses_render_four_distinct_borders
    isolates the border signal, rather than depending on any node in
    sample_root actually being both uncategorised and blocked."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")

    def fill_for(class_attr):
        page.evaluate(
            "cls => document.querySelector('.node').setAttribute('class', cls)",
            class_attr,
        )
        return page.locator(".node rect").first.evaluate("r => getComputedStyle(r).fill")

    ready = fill_for("node cat-5 status-active")
    blocked = fill_for("node cat-5 status-active blocked")
    assert ready != blocked, (ready, blocked)


def test_clicking_the_chip_cycles_the_status(live_server, page, reset_upstream_status):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Upstream"]')
    before = node.get_attribute("class")
    node.locator(".status-chip").click()
    # Unquoted attribute value in the CSS selector: "Upstream" needs no
    # quoting, and quoting it here would require escaping a `"` inside a
    # Python string that is itself embedded in another string -- the
    # brief's literal snippet (`\\"Upstream\\"`) is not valid Python (the
    # first `\\` is a complete escape for one backslash, so the very next
    # `"` closes the outer string early); confirmed by running it verbatim
    # and getting `SyntaxError: unexpected character after line
    # continuation character` at this exact line.
    page.wait_for_function(
        "cls => document.querySelector('.node[data-name=Upstream]').className.baseVal !== cls",
        arg=before,
    )
    assert node.get_attribute("class") != before


def test_clicking_the_chip_does_not_open_the_side_panel(live_server, page, reset_upstream_status):
    """The chip's own click handler stops propagation, so it must never reach
    the node group's click-open scheduling either."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.locator('.node[data-name="Upstream"] .status-chip').click()
    page.wait_for_timeout(300)
    assert "#/project/" not in page.url
    assert page.locator("#project-panel").is_hidden()


def test_conditional_done_collects_and_edits_its_required_note(
    live_server, page, reset_upstream_status
):
    paused = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Upstream", "status": "paused"},
    )
    assert paused.ok, paused.status
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    upstream = page.locator('.node[data-name="Upstream"]')

    upstream.locator(".status-chip").click()

    panel = page.locator("#project-panel")
    panel.wait_for(state="visible")
    assert "status-paused" in upstream.get_attribute("class")
    assert "Conditional done" in panel.locator(".panel-field").first.text_content()
    editor = panel.get_by_label("Notes")
    assert editor.input_value() == ""
    editor.fill("Finish the optional calibration examples.")
    panel.get_by_role("button", name="Save changes").click()

    page.wait_for_function(
        "() => document.querySelector('.node[data-name=Upstream]')"
        ".className.baseVal.includes('status-conditional-done')"
    )
    assert upstream.locator(".status-chip").text_content() == "✓*"
    page.wait_for_function(
        "() => !document.querySelector('.node[data-name=Downstream]')"
        ".className.baseVal.includes('blocked')"
    )
    panel.get_by_text("Finish the optional calibration examples.", exact=True).wait_for()

    panel.get_by_role("button", name="Edit notes").click()
    editor = panel.get_by_label("Notes")
    editor.fill("Finish examples 7–9 and document the exception.")
    panel.get_by_role("button", name="Save changes").click()
    panel.get_by_text("Finish examples 7–9 and document the exception.", exact=True).wait_for()

    detail = page.request.get(f"{live_server}/api/project/Upstream").json()["project"]
    assert detail["status"] == "conditional-done"
    assert detail["conditional_note"] == "Finish examples 7–9 and document the exception."


def test_conditional_done_uses_completed_visual_language(
    live_server, page, reset_downstream_status
):
    response = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={
            "name": "Downstream",
            "status": "conditional-done",
            "conditional_note": "Revisit the archived source notes.",
        },
    )
    assert response.ok, response.status
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Downstream"]')

    assert "status-conditional-done" in node.get_attribute("class")
    assert float(node.locator("rect").get_attribute("height")) == 40
    assert node.locator(".node-due").count() == 0
    assert node.locator(".node-sub").count() == 0
    assert node.locator(".status-chip").text_content() == "✓*"
    assert "line-through" in node.locator(".node-title").evaluate(
        "el => getComputedStyle(el).textDecorationLine"
    )
    conditional_fill = node.locator(".status-chip").evaluate("el => getComputedStyle(el).fill")
    node.evaluate("el => el.setAttribute('class', 'node cat-0 status-done')")
    done_fill = node.locator(".status-chip").evaluate("el => getComputedStyle(el).fill")
    assert conditional_fill == done_fill


def test_a_status_edit_survives_a_fresh_browser_context(
    live_server, page, browser, reset_upstream_status
):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Upstream"]')
    # Without a captured baseline this test can pass vacuously: if every PUT
    # were rejected (e.g. a broken guard), the optimistic update would revert
    # in milliseconds, `after` would equal the untouched original class, and
    # the fresh context would read that same original from the server --
    # green, while persistence is entirely broken.
    before = node.get_attribute("class")
    chip = page.locator('.node[data-name="Upstream"] .status-chip')
    for _ in range(3):
        chip.click()
        page.wait_for_timeout(150)
    after = node.get_attribute("class")
    assert after != before, "three clicks changed nothing -- nothing left to prove persists"

    # A fresh context shares no localStorage. If status survives this, it is
    # server state -- which is the whole point of moving it out of the browser.
    context = browser.new_context()
    try:
        fresh = context.new_page()
        fresh.goto(f"{live_server}/#/")
        fresh.wait_for_selector(".node")
        assert fresh.locator('.node[data-name="Upstream"]').get_attribute("class") == after
    finally:
        context.close()


def test_marking_the_last_blocker_done_unblocks_its_dependent(
    live_server, page, reset_upstream_status
):
    paused = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Upstream", "status": "paused"},
    )
    assert paused.ok, paused.status
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    dependent = page.locator('.node[data-name="Downstream"]')
    assert "blocked" in dependent.get_attribute("class")
    blocker = page.locator('.node[data-name="Upstream"] .status-chip')
    upstream = page.locator('.node[data-name="Upstream"]')
    blocker.click()
    panel = page.locator("#project-panel")
    panel.get_by_label("Notes").fill("Complete the optional exercises later.")
    panel.get_by_role("button", name="Save changes").click()
    page.wait_for_function(
        "() => document.querySelector('.node[data-name=Upstream]')"
        ".className.baseVal.includes('status-conditional-done')"
    )
    blocker.click()
    page.wait_for_function(
        "() => document.querySelector('.node[data-name=Upstream]')"
        ".className.baseVal.includes('status-done')"
    )
    assert "status-done" in upstream.get_attribute("class")
    # Same unquoted-attribute-value fix as above, for the same reason.
    page.wait_for_function(
        "() => !document.querySelector('.node[data-name=Downstream]')"
        ".className.baseVal.includes('blocked')"
    )


def test_a_done_projects_node_collapses_on_reload(live_server, page, reset_downstream_status):
    """buildSubtitle's early return for status === 'done' is the single place
    the collapse is decided (roadmap.js), and it is a named spec deliverable
    with no prior coverage -- deleting that one line left the whole suite
    green. Targets Downstream specifically, not Upstream: Downstream is the
    only sample_root project that carries both a due date and a wrapped
    note, so this is the only node where "collapsed" and "never had a
    subtitle to begin with" are actually distinguishable. Sets status via a
    direct PUT rather than chip-clicking -- chip cycling behaviour already
    has its own coverage above; this test is only about what a 'done'
    payload renders after a reload, which is deliberately one render behind
    any click (see buildSubtitle's own comment)."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    response = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Downstream", "status": "done"},
    )
    assert response.ok, response.status
    page.reload()
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Downstream"]')
    assert "status-done" in node.get_attribute("class")
    # The raw SVG `height` attribute, not .bounding_box() -- the canvas's
    # viewBox scales to fill its container, so on-screen pixel height is not
    # a 1:1 reading of what nodeHeight() actually computed (confirmed
    # empirically: bounding_box() reported ~115px here before this fix,
    # nowhere near either the collapsed 40 or an uncollapsed value in SVG
    # units). NODE_MIN_H (roadmap.js) is 40 for zero subtitle lines, and
    # nodeHeight(0) has no other possible output.
    height = float(node.locator("rect").get_attribute("height"))
    assert height == 40, height
    assert node.locator(".node-due").count() == 0
    assert node.locator(".node-sub").count() == 0
    # The marker is not part of the collapse: it costs no height (it shares
    # the title row with the chip) and it is the only place an issue's text
    # is readable, so hiding it would leave the status strip counting a
    # problem the page shows nowhere. See the spec's "What `done` changes".
    warn = node.locator(".node-warn")
    assert warn.count() == 1, "Downstream's registry issue lost its marker on collapse"
    assert "does not exist" in warn.locator("title").text_content()
    # And it must not land on top of the chip. At the old bottom-right
    # placement a collapsed node put the marker at y=30 against the chip's
    # y=24, at the same x with the same end anchor, so the two glyphs
    # overlapped -- invisible to every count-based assertion.
    warn_box = warn.bounding_box()
    chip_box = node.locator(".status-chip").bounding_box()
    assert warn_box["x"] + warn_box["width"] <= chip_box["x"] + 0.5, (warn_box, chip_box)


def test_a_failed_status_write_reverts_the_chip_and_its_dependents(
    live_server, page, reset_upstream_status
):
    """A failed done -> not-started write restores both node and dependent."""
    done = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Upstream", "status": "done"},
    )
    assert done.ok, done.status
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    upstream = page.locator('.node[data-name="Upstream"]')
    downstream = page.locator('.node[data-name="Downstream"]')
    chip = upstream.locator(".status-chip")

    assert "status-done" in upstream.get_attribute("class")
    assert "blocked" not in downstream.get_attribute("class")

    page.route("**/api/status", lambda route: route.fulfill(status=500))
    chip.click()
    page.wait_for_function(
        "() => document.querySelector('.node[data-name=Upstream]')"
        ".className.baseVal.includes('status-done')"
    )
    assert "status-done" in upstream.get_attribute("class")
    assert "blocked" not in downstream.get_attribute("class")
    page.unroute("**/api/status")


def test_the_wheel_zooms_in(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, -240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) > 100


def test_the_wheel_zooms_out(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, 240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    assert int(page.locator("#zoom-level").inner_text().rstrip("%")) < 100


def test_the_wheel_does_not_scroll_the_page(live_server, page):
    """Without an artificial overflow this assertion cannot fail: the app's
    own layout (body { height: 100vh }, #main and #tree each scrolling
    internally via their own overflow-y) never lets the outer document grow
    taller than the viewport, so window.scrollY stays 0 regardless of
    whether the wheel handler calls preventDefault -- confirmed empirically
    by dropping preventDefault and setting passive: true, which left this
    test green. Forcing document.body's min-height past the viewport here
    makes the document genuinely scrollable, so a wheel default that reaches
    the page (the mutation above) actually moves window.scrollY, and the
    assertion is a real regression guard rather than a vacuous one."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.evaluate("() => { document.body.style.minHeight = '2000px'; }")
    page.mouse.move(400, 300)
    page.mouse.wheel(0, 240)
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.scrollY") == 0


def test_zoom_stays_within_its_limits(live_server, page):
    """Both halves must first confirm the level actually moved off 100% --
    otherwise a wheel handler that never fires at all (unregistered listener,
    a swallowed error, anything that leaves #zoom-level stuck at '100%')
    would satisfy `100 <= 250` and `100 >= 35` trivially and this test would
    report green for a total regression of the feature it is named after.
    The bound checks below only mean anything once that movement is proven."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    page.mouse.move(400, 300)
    for _ in range(40):
        page.mouse.wheel(0, -240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    level = int(page.locator("#zoom-level").inner_text().rstrip("%"))
    assert level > 100, level
    assert level <= 250, level
    for _ in range(80):
        page.mouse.wheel(0, 240)
    page.wait_for_function(
        "() => parseInt(document.getElementById('zoom-level').textContent, 10) < 100"
    )
    level = int(page.locator("#zoom-level").inner_text().rstrip("%"))
    assert level < 100, level
    assert level >= 35, level


def test_the_point_under_the_cursor_stays_put(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    box = page.locator('.node[data-name="Upstream"] rect').bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -240)
    page.wait_for_function("() => document.getElementById('zoom-level').textContent !== '100%'")
    after = page.locator('.node[data-name="Upstream"] rect').bounding_box()
    acx, acy = after["x"] + after["width"] / 2, after["y"] + after["height"] / 2
    # Anchored zoom: the point under the pointer does not slide away from it.
    assert abs(acx - cx) < 12 and abs(acy - cy) < 12


def test_a_project_with_both_a_due_date_and_a_note_shows_both(live_server, page):
    """A fixed 62px node used to force renderRoadmap to pick `project.due ||
    project.note` for the subtitle -- a project carrying both fields showed
    only the due date, and its note was silently dropped. Nodes now grow to
    fit, so that tradeoff is gone: Downstream (sample_root) carries both, and
    both must reach the node -- the due line above the wrapped note, not
    whichever `||` would have picked."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    node = page.locator('.node[data-name="Downstream"]')
    # .inner_text() requires an HTMLElement; .node-due is an SVG <text>, so
    # use .text_content(), which works on any node regardless of namespace.
    assert node.locator(".node-due").text_content() == "Due 2026-08-17"
    assert node.locator(".node-sub tspan").count() >= 2


def test_isolated_projects_leave_the_graph(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator('.node[data-name="Standalone"]').count() == 0


def test_isolated_projects_appear_in_a_category_container(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    assert page.locator('#categories [data-name="Standalone"]').count() == 1


def test_each_category_gets_its_own_container(live_server, page):
    """categories.js groups into a Map keyed on category name, so section
    titles are unique by construction -- a bare `len(titles) ==
    len(set(titles))` is true for every possible output of this
    implementation, including a total collapse into one container (["ops"]
    passes just as trivially as ["ops", "infra"] does). The real claim this
    test's name makes is that Standalone and Backlog -- sample_root's two
    isolated projects, in different categories -- land in *different*
    containers, each titled after its own project's `category`. Assert that
    directly: each project's own containing .category section, not merely
    something present somewhere under #categories.

    .text_content(), not .inner_text()/.all_inner_texts(): `.category h3` is
    `text-transform: uppercase` (app.css), and .inner_text() reflects
    rendered text -- it read back "OPS"/"INFRA", not the "ops"/"infra"
    categories.js actually wrote via .textContent. .text_content() reports
    the raw DOM text, unaffected by CSS.
    """
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    titles = page.locator("#categories .category h3").all_text_contents()
    assert sorted(titles) == ["infra", "ops", "research"], titles

    standalone_section = page.locator(
        "#categories .category", has=page.locator('[data-name="Standalone"]')
    )
    assert standalone_section.locator("h3").text_content() == "ops"

    backlog_section = page.locator(
        "#categories .category", has=page.locator('[data-name="Backlog"]')
    )
    assert backlog_section.locator("h3").text_content() == "infra"


def test_a_category_container_is_coloured_like_its_categorys_node(live_server, page):
    """ "One container per category, coloured to match that category's node
    colour" (the spec) was silently dropped: categories.js set a bare
    `className = 'category'`.

    It is not trivially recoverable, which is why it went missing.
    roadmap.js assigned colour by insertion order over the projects it was
    handed, and app.js hands it only the connected ones -- so a category
    whose members are all isolated was never numbered at all, and one with
    members on both sides would be numbered differently by each renderer.
    app.js now builds the order map over the whole payload (palette.js) and
    passes the same map to both.

    "Reading list" (isolated, category "research") and "Downstream" (a graph
    node, same category) are what make that testable: the assertion is on the
    computed colour, not just the shared class name, so a cat-N class with no
    CSS rule behind it on the column side would still fail.
    """
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    node = page.locator('.node[data-name="Downstream"]')
    node_class = set(node.get_attribute("class").split())
    # The colour now lives on each entry box (app.css's .entry.cat-N),
    # matching a graph node's own .cat-N rect -- not on the group's heading
    # container, which is deliberately uncoloured (a "non-box title").
    entry = page.locator('#categories [data-name="Reading list"]')
    assert node_class & set(entry.get_attribute("class").split()) & {f"cat-{n}" for n in range(6)}
    stroke = node.locator("rect").evaluate("r => getComputedStyle(r).stroke")
    border = entry.evaluate("e => getComputedStyle(e).borderTopColor")
    assert stroke == border, (stroke, border)


def test_two_categories_in_the_column_are_coloured_differently(live_server, page):
    """A shared order map that handed every category the same class would
    satisfy the agreement test above and still be useless."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    borders = page.locator("#categories .entry").evaluate_all(
        "entries => entries.map((e) => getComputedStyle(e).borderTopColor)"
    )
    assert len(set(borders)) == len(borders), borders


def test_the_category_column_is_hidden_when_nothing_is_isolated(page, layout_server):
    """renderCategories returns early with nothing to draw when every project
    is in the graph, and #categories was unhidden regardless -- 240px of
    canvas lost to an empty bordered box. layout_root's four projects are all
    connected. "Permanent, not another toggle" (the spec) is about the
    affordance, not about rendering an empty container."""
    page.goto(layout_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#categories .category").count() == 0
    assert page.locator("#categories").is_hidden()


def test_a_category_entry_opens_the_side_panel(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    page.locator('#categories [data-name="Standalone"] .entry-name').click()
    page.wait_for_selector("#project-panel:visible", timeout=5000)
    assert page.locator("#project-panel h2").inner_text() == "Standalone"


def test_double_clicking_a_category_entry_opens_its_folder(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    page.locator('#categories [data-name="Standalone"] .entry-name').dblclick()
    page.wait_for_function("() => location.hash.startsWith('#/browse/')", timeout=5000)
    page.wait_for_selector(".listing", timeout=5000)
    assert page.locator("#project-panel").is_hidden()


def test_habit_cards_show_unlock_state_without_a_status_chip(habit_server, page):
    page.goto(f"{habit_server}/#/")
    ready = page.locator('#categories [data-name="Ready Practice"]')
    locked = page.locator('#categories [data-name="Locked Practice"]')

    ready.wait_for()
    assert ready.locator(".entry-state").inner_text() == "Ready"
    assert locked.locator(".entry-state").inner_text() == "Locked · Course"
    assert ready.locator(".status-chip").count() == 0
    assert locked.locator(".status-chip").count() == 0


def test_habits_stay_out_of_the_graph_even_if_isolation_metadata_is_wrong(live_server, page):
    page.route(
        "**/api/projects",
        lambda route: route.fulfill(
            json={
                "root": "fixture",
                "registry": True,
                "issues": [],
                "projects": [
                    {
                        "name": "Finite",
                        "paths": ["notes"],
                        "blocked_by": [],
                        "category": "course",
                        "due": None,
                        "note": None,
                        "status": "active",
                        "isolated": True,
                        "is_habit": False,
                        "habit_unlocked": False,
                        "habit_locked_by": [],
                    },
                    {
                        "name": "Practice",
                        "paths": ["notes"],
                        "blocked_by": ["Finite"],
                        "category": "habit",
                        "due": None,
                        "note": None,
                        "status": "not-started",
                        "isolated": False,
                        "is_habit": True,
                        "habit_unlocked": False,
                        "habit_locked_by": ["Finite"],
                    },
                ],
            }
        ),
    )

    page.goto(f"{live_server}/#/")
    habit = page.locator('#categories [data-name="Practice"]')

    habit.wait_for()
    assert page.locator('.node[data-name="Practice"]').count() == 0
    assert page.locator("#roadmap-canvas .edge").count() == 0


def test_a_habit_quick_look_uses_unlock_language(habit_server, page):
    page.goto(f"{habit_server}/#/")
    page.locator('#categories [data-name="Locked Practice"] .entry-name').click()
    panel = page.locator("#project-panel")

    panel.wait_for()
    assert panel.locator(".panel-habit-state").inner_text() == "Locked · Course"
    assert panel.get_by_text("Not started", exact=True).count() == 0
    assert panel.locator(".panel-open").inner_text() == "Open habit files"


def test_habit_gates_never_render_as_roadmap_edges(habit_server, page):
    page.goto(f"{habit_server}/#/")
    page.locator('.node[data-name="Roadmap root"]').wait_for()

    node_names = page.locator("#roadmap-canvas .node").evaluate_all(
        "nodes => nodes.map((node) => node.dataset.name)"
    )
    assert sorted(node_names) == ["Roadmap leaf", "Roadmap root"]
    assert page.locator("#roadmap-canvas .edge").count() == 1
    assert page.locator('#categories [data-name="Course"]').count() == 1


def test_double_clicking_a_habit_opens_its_folder_without_writing(habit_server, habit_root, page):
    before = folder_snapshot(habit_root)
    page.goto(f"{habit_server}/#/")
    page.locator('#categories [data-name="Ready Practice"] .entry-name').dblclick()

    page.wait_for_function(
        "() => location.hash === '#/browse/habits/ready'",
        timeout=5000,
    )
    page.wait_for_selector(".listing", timeout=5000)
    assert folder_snapshot(habit_root) == before


@pytest.fixture
def habit_course_paused(habit_server, page):
    before = page.request.get(f"{habit_server}/api/projects").json()
    original = next(row["status"] for row in before["projects"] if row["name"] == "Course")
    response = page.request.put(
        f"{habit_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Course", "status": "paused"},
    )
    assert response.ok, response.text()
    yield
    response = page.request.put(
        f"{habit_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Course", "status": original},
    )
    assert response.ok, response.text()


def test_finishing_a_gate_updates_the_habit_without_reloading(
    habit_server, page, habit_course_paused
):
    page.goto(f"{habit_server}/#/")
    habit_state = page.locator('#categories [data-name="Locked Practice"] .entry-state')
    assert habit_state.inner_text() == "Locked · Course"

    page.locator('#categories [data-name="Course"] .status-chip').click()
    panel = page.locator("#project-panel")
    panel.get_by_label("Notes").fill("Repeat the final drill later.")
    panel.get_by_role("button", name="Save changes").click()

    page.wait_for_function(
        "() => document.querySelector('[data-name=\"Locked Practice\"] .entry-state')?.textContent"
        " === 'Ready'",
        timeout=5000,
    )


def test_a_failed_gate_status_write_relocks_the_habit(habit_server, page, habit_course_paused):
    page.goto(f"{habit_server}/#/")
    page.route("**/api/status", lambda route: route.fulfill(status=500))

    page.locator('#categories [data-name="Course"] .status-chip').click()
    panel = page.locator("#project-panel")
    panel.get_by_label("Notes").fill("Repeat the final drill later.")
    panel.get_by_role("button", name="Save changes").click()

    page.wait_for_function(
        "() => document.querySelector('[data-name=\"Course\"]')?.classList"
        ".contains('status-paused')",
        timeout=5000,
    )
    assert (
        page.locator('#categories [data-name="Locked Practice"] .entry-state').inner_text()
        == "Locked · Course"
    )


def test_the_details_toggle_is_gone(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    assert page.locator("#rail-toggle").count() == 0
    assert page.locator("#rail").count() == 0


def test_the_status_strip_reports_registry_issues(live_server, page):
    page.goto(f"{live_server}/#/")
    page.wait_for_selector(".node")
    # sample_root's registry has at least one issue; the rail used to be the
    # only place it was visible.
    assert "issue" in page.locator("#status").inner_text()


def test_backlogs_issue_is_readable_from_its_category_entry(live_server, page):
    """The graph's own node gets a `!` marker with the issue text in a
    <title> tooltip (roadmap.js); an isolated project has no node to carry
    it, so without an equivalent here, Backlog's issue -- the very one
    test_the_status_strip_reports_registry_issues depends on -- would exist
    only as a number in the status strip, readable nowhere on the page."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    entry = page.locator('#categories [data-name="Backlog"]')
    warn = entry.locator(".entry-warn")
    assert warn.count() == 1
    assert "Vanished" in warn.get_attribute("title")


def test_a_failed_status_write_reverts_the_category_chip(live_server, page):
    """The rollback path in categories.js's chip handler had no coverage at
    all -- every existing rollback test targets a graph node's chip, and
    every `.status-chip` locator in this file before this test is scoped to
    `.node[...]`. Mirrors
    test_a_failed_status_write_reverts_the_chip_and_its_dependents's shape
    (a real state change first, then a broken one, so the second click has a
    non-trivial state to revert to -- a single click against an
    always-failing endpoint cannot distinguish "reverted correctly" from "the
    whole click handler is inert"), but both requests are stubbed here rather
    than letting the first one reach the real backend, so this test needs no
    server-state cleanup afterward."""
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    entry = page.locator('#categories [data-name="Standalone"]')
    chip = entry.locator(".status-chip")
    before_class = entry.get_attribute("class")

    calls = {"n": 0}

    def handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            route.fulfill(status=500)

    page.route("**/api/status", handler)

    chip.click()
    page.wait_for_function(
        "cls => document.querySelector('#categories [data-name=\"Standalone\"]').className !== cls",
        arg=before_class,
    )
    succeeded_class = entry.get_attribute("class")
    succeeded_glyph = chip.inner_text()
    assert succeeded_class != before_class

    chip.click()
    page.wait_for_timeout(300)
    assert entry.get_attribute("class") == succeeded_class
    assert chip.inner_text() == succeeded_glyph


# Installed before navigation, so it is in place for the very first click.
# Records, in the page, when each /api/status request starts and when it
# settles, and holds each one open for SETTLE_MS after the response arrives so
# that overlapping writes overlap by a margin no scheduling jitter can close.
#
# The delay lives here rather than in the route handler on purpose. Playwright's
# Python sync API is greenlet-based and single-threaded: a route handler runs
# inside a task on the driver's own event loop with no await, so a blocking
# time.sleep there stalls the loop, and neither the next route event nor the
# next driver call (a chip.click(), say) can be delivered until it returns.
# Measured from the driver, "the second request started after the first
# finished" is then true of the harness whatever the client does. Awaiting
# inside the page instead measures the client.
FETCH_PROBE = """
window.__statusFetches = [];
const realFetch = window.fetch;
const settle = (entry) => new Promise((resolve) => window.setTimeout(resolve, %d)).then(() => {
  entry.end = performance.now();
});
window.fetch = function (...args) {
  const target = args[0];
  const url = String(target && target.url ? target.url : target);
  if (!url.includes('/api/status')) return realFetch.apply(window, args);
  const entry = { start: performance.now() };
  window.__statusFetches.push(entry);
  return realFetch.apply(window, args).then(
    (response) => settle(entry).then(() => response),
    (error) => settle(entry).then(() => { throw error; }),
  );
};
"""
SETTLE_MS = 80


def click_chip(page, selector, times):
    """`times` clicks in one page turn, with no driver round trip between them.

    Three separate chip.click() calls cannot prove anything about queueing:
    each is a driver call that waits for the page to be idle, so the second
    click cannot even be dispatched until the first click's write is long
    settled. Dispatching them from inside one evaluate() is what makes them
    genuinely rapid -- all three handlers run synchronously, in the same task,
    before the page yields to anything.
    """
    page.evaluate(
        """([selector, times]) => {
            const chip = document.querySelector(selector);
            for (let i = 0; i < times; i += 1) chip.click();
        }""",
        [selector, times],
    )


def test_rapid_clicks_on_the_category_chip_serialize_their_writes(
    live_server, page, reset_standalone_status
):
    """writeStatus (status.js) is a shared, module-scoped queue used by both
    roadmap.js and categories.js, and this is the only test of the ordering
    guarantee it exists for.

    The measurement is taken in the page (FETCH_PROBE above), not in the
    route handler, so what it observes is the client's own behaviour: when
    each PUT left the page and when it settled. Every request's start must
    land at or after the previous request's end -- with the queue removed,
    all three clicks issue their fetch synchronously in the same task and the
    three intervals overlap almost exactly.

    The two payload assertions are kept but carry nothing on their own:
    nextStatus is applied synchronously on each click before its fetch is
    issued, so three distinct statuses all naming Standalone arrive at the
    server whether the writes are queued or not.
    """
    page.add_init_script(FETCH_PROBE % SETTLE_MS)
    seeded = page.request.put(
        f"{live_server}/api/status",
        headers={"X-Armoire": "1"},
        data={"name": "Standalone", "status": "done"},
    )
    assert seeded.ok, seeded.status
    bodies = []

    def handler(route):
        bodies.append(route.request.post_data_json)
        # Fulfilled immediately: the driver's loop must stay free, or the
        # clicks and the polling below cannot be delivered while a write is
        # in flight. The artificial latency is the page's, not the harness's.
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/status", handler)
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    click_chip(page, '#categories [data-name="Standalone"] .status-chip', 3)

    page.wait_for_function(
        "() => window.__statusFetches.length === 3"
        " && window.__statusFetches.every((entry) => entry.end !== undefined)",
        timeout=15000,
    )
    log = page.evaluate("() => window.__statusFetches")
    assert len(log) == 3, log
    for earlier, later in zip(log, log[1:], strict=False):
        assert later["start"] >= earlier["end"], log

    assert {body["name"] for body in bodies} == {"Standalone"}, bodies
    assert len({body["status"] for body in bodies}) == 3, bodies


def test_a_stale_failed_write_does_not_roll_back_over_a_newer_one(live_server, page):
    """writeToken (status.js) had no direct coverage: every rollback test
    above exercises a failure that *is* the latest click for its project, the
    case the guard lets through.

    Two clicks in one task, with only the first write failing. By the time
    that failure is caught, the second click has already moved the optimistic
    state past it and queued its own write, so rolling back to what the first
    click saw as "previous" would put the chip on a status the server never
    held for either click -- and would then disagree with the write that
    actually succeeded. Without the token check the rollback fires and the
    chip lands back on its starting status.

    Both requests are stubbed, so the server's state is untouched and this
    test needs no cleanup. The expected status is derived from whatever the
    chip starts on rather than assumed, so the test does not depend on the
    order it runs in.
    """
    calls = {"n": 0}

    def handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=500)
        else:
            route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/status", handler)
    page.goto(f"{live_server}/#/")
    page.wait_for_selector("#categories .category")
    entry = page.locator('#categories [data-name="Standalone"]')
    before = entry.get_attribute("class")
    started = next(s for s in STATUS_ORDER if f"status-{s}" in before)
    expected = STATUS_ORDER[(STATUS_ORDER.index(started) + 2) % len(STATUS_ORDER)]
    # The entry's cat-N class never changes across a status write -- only its
    # status-* class does (categories.js) -- so read it once from the
    # baseline rather than hardcoding a category index the registry's own
    # ordering assigns.
    cat_class = next(c for c in before.split() if c.startswith("cat-"))

    click_chip(page, '#categories [data-name="Standalone"] .status-chip', 2)
    deadline = time.monotonic() + 10
    while calls["n"] < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert calls["n"] == 2, calls
    # Long enough for a rollback to have landed if one were going to.
    page.wait_for_timeout(300)

    assert entry.get_attribute("class") == f"entry {cat_class} status-{expected}", (
        before,
        entry.get_attribute("class"),
    )


def test_the_registry_button_is_in_the_footer_on_the_roadmap(page, live_server):
    open_roadmap(page, live_server)
    button = page.locator("#status .registry-open")
    assert button.is_visible()
    assert button.inner_text() == "Edit registry"


def test_the_registry_button_is_in_the_footer_on_the_browse_view(page, live_server):
    """The browse view matters as much as the roadmap: a folder with only a
    stub registry is bounced out of the roadmap into the file browser, so a
    roadmap-only button would be missing exactly when it is needed to declare
    a first project."""
    page.goto(f"{live_server}/#/browse/")
    page.wait_for_selector("#tree", state="visible", timeout=15000)
    assert page.locator("#status .registry-open").is_visible()


def test_clicking_the_registry_button_asks_the_server_to_open_it(page, live_server):
    calls = []

    def stub(route, request):
        # Never let this reach the real endpoint: it would launch an editor
        # on whatever machine is running the suite.
        calls.append(request.method)
        route.fulfill(status=200, json={"opened": True})

    page.route("**/api/registry/open", stub)
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert calls == ["POST"]


def test_the_registry_button_sends_the_guard_header(page, live_server):
    """Without X-Armoire the server refuses. A button that always 403s is a
    button that never works."""
    seen = []

    def stub(route, request):
        seen.append(request.headers.get("x-armoire"))
        route.fulfill(status=200, json={"opened": True})

    page.route("**/api/registry/open", stub)
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.05)
    assert seen == ["1"]


def test_the_error_box_carries_a_registry_button(page, broken_registry_server):
    page.goto(f"{broken_registry_server}/#/")
    page.wait_for_selector("#roadmap-message .error", timeout=15000)
    assert page.locator("#roadmap-message .error .registry-open").is_visible()


def test_a_failed_launch_falls_back_to_the_path(page, live_server):
    """No handler registered for .toml. The button is replaced by the path
    and a copy button -- the worst case still beats hunting for the hash."""
    page.route(
        "**/api/registry/open",
        lambda route: route.fulfill(
            status=500, json={"detail": "no application is associated with .toml"}
        ),
    )
    open_roadmap(page, live_server)
    page.locator("#status .registry-open").click()
    fallback = page.locator("#status .registry-fallback")
    fallback.wait_for(timeout=5000)
    assert "no application is associated" in fallback.inner_text()
    assert page.locator("#status .registry-fallback code").inner_text().endswith("registry.toml")
    # Replaced, not appended: a button that just failed must not still look
    # clickable.
    assert page.locator("#status .registry-open").count() == 0
