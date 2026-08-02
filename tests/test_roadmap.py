"""The roadmap, exercised in a real browser."""

import time


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
    warning marker even though it has a real issue against it."""
    page.goto(colon_name_server)
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#roadmap .node-warn").count() == 1


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
    import hashlib

    def snapshot():
        # mtime as well as sha256. This is the read-only test that reaches the
        # git subprocess (open_roadmap fetches /api/projects, which runs
        # activity_for over every declared path), and a pure-metadata touch --
        # exactly what an ill-judged `os.utime` or a git operation that rewrites
        # an index would produce -- is invisible to a content hash alone.
        return {
            p.relative_to(sample_root).as_posix(): (
                p.stat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(sample_root.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 90, 40)
    page.wait_for_timeout(300)
    assert snapshot() == before


def test_zoom_controls_change_the_reported_level(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#zoom-in").click()
    assert page.locator("#zoom-level").inner_text() != "100%"


def test_dragging_a_node_does_not_open_its_project(page, live_server):
    """The whole point of suppressClick: a reposition must not navigate away."""
    open_roadmap(page, live_server)
    drag_node(page, "Upstream", 120, 60)
    page.wait_for_timeout(400)
    assert page.evaluate("location.hash") in ("", "#/")
    assert page.locator("#roadmap .node").first.is_visible()


def test_clicking_a_node_without_dragging_still_opens_it(page, live_server):
    """suppressClick must not suppress a genuine click."""
    open_roadmap(page, live_server)
    page.locator('#roadmap .node[data-name="Upstream"]').click()
    page.wait_for_function("() => location.hash === '#/project/Upstream'", timeout=5000)


def test_the_rail_is_collapsed_by_default(page, live_server):
    open_roadmap(page, live_server)
    assert page.locator("#rail").is_hidden()


def test_the_rail_toggles_open(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail:visible", timeout=5000)
    assert page.locator("#rail").is_visible()


def test_the_rail_ranks_projects_by_commit_count(page, live_server):
    """The brief's version asserted only that the rail was non-empty, which
    passes with the list in any order, or reversed. sample_root's own two
    projects both compute to zero commits -- there is no git history under
    the pytest tmp path, confirmed by calling project_rows() against a
    replica of the fixture -- so real fixture data ties and cannot
    distinguish a correct sort from a reversed or removed one. This stubs
    /api/projects with commit counts that actually differ, listed in an
    order that is neither sorted nor reverse-sorted, so a removed or
    inverted sort both change the rendered order."""
    import json

    stub = {
        "root": "stub-root",
        "projects": [
            {
                "name": "Mid",
                "paths": [],
                "blocked_by": [],
                "category": None,
                "due": None,
                "note": None,
                "commits": 5,
                "last": None,
            },
            {
                "name": "Low",
                "paths": [],
                "blocked_by": [],
                "category": None,
                "due": None,
                "note": None,
                "commits": 2,
                "last": None,
            },
            {
                "name": "High",
                "paths": [],
                "blocked_by": [],
                "category": None,
                "due": None,
                "note": None,
                "commits": 9,
                "last": None,
            },
        ],
        "issues": [],
    }
    page.route(
        "**/api/projects",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(stub)
        ),
    )
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail li", timeout=5000)
    items = page.locator("#rail li").all_text_contents()
    activity = [i for i in items if "—" in i]
    assert len(activity) == 3, activity
    counts = [int(i.rsplit("—", 1)[1].strip()) for i in activity]
    assert counts == [9, 5, 2], counts


def test_the_rail_lists_blocked_projects_with_their_blocker(page, live_server):
    """The brief's version asserted both project names appeared somewhere in
    the rail, which passes even with an empty Blocked section: both names
    already appear in the Activity section directly above. Scope the
    assertion to the blocked entry rail.js actually renders, in the
    "Downstream ← Upstream" form the sample registry's one edge produces."""
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail li", timeout=5000)
    items = page.locator("#rail li").all_text_contents()
    blocked = [i for i in items if "←" in i]
    assert blocked == ["Downstream ← Upstream"], blocked


def test_the_rail_open_state_survives_a_reload(page, live_server):
    open_roadmap(page, live_server)
    page.locator("#rail-toggle").click()
    page.wait_for_selector("#rail:visible", timeout=5000)
    page.reload()
    page.wait_for_selector("#roadmap .node", timeout=15000)
    assert page.locator("#rail").is_visible()


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
    """Each visit re-runs renderRoadmap/initRail against the same persistent
    #roadmap-canvas and #rail-toggle elements. Without aborting the previous
    run's listeners they pile up for the lifetime of the page -- but a
    behavioural check on either element's final visible state cannot catch
    it: every surviving duplicate listener holds its own independent `open`
    (rail) or `positions`/`dragging` (canvas) closure that starts at the
    same value and evolves in lockstep with all the others on every real
    event, so the rendered result is coincidentally correct no matter how
    many copies are attached (verified empirically: the dispatch's own
    suggested assertion -- click once after three revisits and require the
    rail's visibility to have flipped -- passes against the unfixed code
    too). The actual, catchable symptom is duplicated *work*: each surviving
    listener independently calls its own write to localStorage, so after N
    revisits a single canvas drag writes the layout key N+1 times, and a
    single rail-toggle click writes the rail key N+1 times, instead of once
    each. Spying on Storage.prototype.setItem counts both directly instead
    of guessing at an observable side effect. Both prefixes are tracked
    through the one wrapper rather than two separate spies -- there is only
    one thing being proven (accumulated writes per surviving listener) and
    one wrapper installed once reads more directly than re-deriving the same
    instrumentation twice.

    Coordinator review of this test's first version found it exercised only
    the canvas listeners (via the drag) and never clicked #rail-toggle, so a
    signal dropped from only the toggle's addEventListener call in rail.js
    would have shipped undetected -- the click below, and its own write
    count, close that gap.

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
        page.evaluate("window.location.hash = '/project/Upstream'")
        page.wait_for_function("() => location.hash === '#/project/Upstream'")
        page.evaluate("window.location.hash = '/'")
        page.wait_for_selector("#roadmap .node[data-name='Upstream']", timeout=15000)
        # One showRoadmap() call makes exactly one AbortController: the
        # initial open_roadmap() plus this being the (i+1)th revisit.
        page.wait_for_function(f"() => window.__acCreates === {i + 2}", timeout=15000)

    page.evaluate(
        """() => {
            window.__writes = { layout: 0, rail: 0 };
            const original = Storage.prototype.setItem;
            Storage.prototype.setItem = function (key, value) {
                if (key.startsWith('armoire:layout:')) window.__writes.layout += 1;
                if (key.startsWith('armoire:rail:')) window.__writes.rail += 1;
                return original.call(this, key, value);
            };
        }"""
    )

    page.locator("#rail-toggle").click()
    rail_writes = page.evaluate("window.__writes.rail")
    assert rail_writes == 1, rail_writes

    drag_node(page, "Upstream", 80, 30)
    page.wait_for_timeout(300)
    layout_writes = page.evaluate("window.__writes.layout")
    assert layout_writes == 1, layout_writes


def test_project_detail_shows_blockers_and_what_it_blocks(page, live_server):
    page.goto(f"{live_server}/#/project/Upstream")
    page.wait_for_selector(".project-detail", timeout=10000)
    text = page.locator(".project-detail").inner_text()
    assert "Downstream" in text


def test_project_detail_lists_files(page, live_server):
    page.goto(f"{live_server}/#/project/Downstream")
    page.wait_for_selector(".project-detail a", timeout=10000)
    assert page.locator(".project-detail a").count() >= 1


def test_a_file_link_in_the_detail_reaches_the_viewer(page, live_server):
    page.goto(f"{live_server}/#/project/Downstream")
    page.wait_for_selector(".project-detail a", timeout=10000)
    page.locator(".project-detail a").first.click()
    page.wait_for_function("() => location.hash.startsWith('#/browse/')", timeout=5000)


def test_an_unknown_project_shows_an_error_not_a_blank_page(page, live_server):
    page.goto(f"{live_server}/#/project/Ghost")
    page.wait_for_selector("#content .error", timeout=10000)
    assert page.locator("#content .error").inner_text().strip() != ""


def test_project_detail_renders_structured_commit_rows(page, live_server):
    """The detail view is what a node click lands on; unstyled defaults undercut
    the whole point of the roadmap screen."""
    page.goto(f"{live_server}/#/project/Downstream")
    page.wait_for_selector(".project-detail", timeout=10000)
    assert page.locator(".project-detail .relations").count() == 1
    # The commit-row assertions that used to sit here were guarded behind
    # `if rows.count():`, and against live_server that count is always zero --
    # sample_root has no git history at all, so the block never ran and read as
    # coverage it was not providing. The real check is
    # test_project_detail_commit_rows_have_sha_subject_and_when, against
    # committed_server.


def test_a_long_commit_subject_does_not_push_the_timestamp_out_of_its_row(page, live_server):
    """Commit subjects come from arbitrary repositories, so the row has to hold
    against an unbounded one: the subject must ellipsize and `.when`
    (margin-left: auto) must stay inside the row that `.project-detail ul`
    clips with overflow: hidden.

    `.subject` is a flex item with the default `flex: 0 1 auto` and a computed
    `min-width: auto`, which normally cannot shrink below its content's
    intrinsic width -- but it also sets `overflow: hidden`, and per CSS Flexbox
    4.5 a flex item whose overflow is anything but `visible` gets an automatic
    minimum size of zero. So it does shrink and the ellipsis does fire; an
    explicit `min-width: 0` would be a no-op here. Measured: scrollWidth 3398
    against clientWidth 771, `.when` at x=1156 inside a row ending at 1203.

    What this test guards is that pairing. Forcing `.subject` back to
    `overflow: visible` widens it to its full 3398px and throws `.when` out to
    x=3783, ~2.5k past the clip edge -- the timestamp vanishes.

    Stubbed rather than committed to a fixture repo: the subject has to be long
    enough to overflow at any viewport, and no real fixture commit is. The
    payload shape is project.js's contract for /api/project/<name>.
    """
    import json

    stub = {
        "project": {
            "name": "Long",
            "paths": ["notes"],
            "blocked_by": [],
            "category": None,
            "due": None,
            "note": None,
        },
        "blocks": [],
        "commits": [
            {
                "sha": "abc1234",
                "subject": "refactor the entire ingestion pipeline and " * 12,
                "when": time.time(),
            }
        ],
        "files": [],
    }
    page.route(
        "**/api/project/Long",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(stub)
        ),
    )
    page.goto(f"{live_server}/#/project/Long")
    page.wait_for_selector(".project-detail li.commit", timeout=10000)
    row = page.locator(".project-detail li.commit").first
    when = row.locator(".when")
    assert when.count() == 1

    # The subject is genuinely truncated, not merely narrow.
    overflowed = row.locator(".subject").evaluate("el => el.scrollWidth > el.clientWidth")
    assert overflowed, "a 500-character subject should be clipped, so the ellipsis can show"

    row_box = row.bounding_box()
    when_box = when.bounding_box()
    # 1px of slack for subpixel layout, nothing more.
    assert when_box["x"] >= row_box["x"] - 1, (when_box, row_box)
    assert when_box["x"] + when_box["width"] <= row_box["x"] + row_box["width"] + 1, (
        when_box,
        row_box,
    )


def test_project_detail_commit_rows_have_sha_subject_and_when(page, committed_server):
    """live_server's sample_root has no git history at all (neither Downstream
    nor Upstream has a single commit), so the guarded check above never
    actually exercises the commit-row branch. committed_server's one project
    has two real commits, so this positively verifies the .commit / .sha /
    .subject / .when structure project.js renders, rather than leaving it
    unverified."""
    page.goto(f"{committed_server}/#/project/Worked")
    page.wait_for_selector(".project-detail li.commit", timeout=10000)
    rows = page.locator(".project-detail li.commit")
    assert rows.count() == 2
    first = rows.first
    assert first.locator(".sha").count() == 1
    assert first.locator(".subject").count() == 1
    assert first.locator(".when").count() == 1
    assert first.locator(".subject").inner_text() == "second worked commit"
