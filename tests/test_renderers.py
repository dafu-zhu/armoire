"""Every renderer, exercised against the sample folder in a real browser."""


def open_path(page, live_server, path):
    page.goto(f"{live_server}/#/browse/{path}")
    page.wait_for_selector("#content *")


def test_directory_shows_a_listing(page, live_server):
    open_path(page, live_server, "notes")
    assert page.locator(".listing").count() == 1
    assert "buried" not in page.locator(".listing").inner_text()
    assert "deep" in page.locator(".listing").inner_text()


def test_directory_renders_its_readme_below_the_listing(page, live_server):
    open_path(page, live_server, "notes")
    page.wait_for_selector(".markdown-body")
    assert "Nested folder readme" in page.locator(".markdown-body").inner_text()


def test_markdown_renders_headings(page, live_server):
    open_path(page, live_server, "README.md")
    assert page.locator(".markdown-body h1").inner_text() == "Sample Folder"


def test_markdown_renders_math_through_katex(page, live_server):
    open_path(page, live_server, "README.md")
    page.wait_for_selector(".katex")
    assert page.locator(".katex").count() >= 2


def test_markdown_renders_mermaid_as_svg(page, live_server):
    open_path(page, live_server, "README.md")
    page.wait_for_selector(".mermaid-slot svg")
    assert page.locator(".mermaid-slot svg").count() == 1


def test_markdown_rewrites_relative_links_to_in_app_routes(page, live_server):
    open_path(page, live_server, "README.md")
    link = page.locator('.markdown-body a[href="#/browse/notes"]')
    assert link.count() == 1
    link.click()
    page.wait_for_selector(".listing")


def test_markdown_links_to_a_percent_named_file_navigate(page, live_server):
    """rewriteLinks (renderers/markdown.js) is a third hash write site,
    distinct from navigate() and the breadcrumb links: an unencoded href
    there yields a hash currentRoute() cannot decode, which is a dead link."""
    open_path(page, live_server, "links.md")
    link = page.locator('.markdown-body a[href="#/browse/100%25.md"]')
    assert link.count() == 1
    link.click()
    # The source page already has its own .markdown-body, so wait for the
    # *content* to change rather than for the selector to merely exist --
    # otherwise the wait would pass immediately against the stale element.
    page.wait_for_function(
        "() => document.querySelector('.markdown-body')?.innerText.includes('Percent Only')",
        timeout=5000,
    )
    assert page.locator("#content .error").count() == 0


def test_markdown_marks_a_link_that_leads_nowhere(page, live_server):
    open_path(page, live_server, "links.md")
    dead = page.locator(".markdown-body a.broken")
    dead.wait_for()
    assert dead.count() == 1
    assert dead.inner_text() == "gone"
    assert dead.get_attribute("title") == "missing: gone.md"


def test_a_broken_link_carries_no_href_at_all(page, live_server):
    """Removing the href, rather than only swallowing the click, is what makes
    the gesture inert for every route into it -- a middle click, a ctrl click
    and Enter on a focused link all bypass a click handler and would each
    still open the dead path."""
    open_path(page, live_server, "links.md")
    page.locator(".markdown-body a.broken").wait_for()
    assert page.locator(".markdown-body a.broken").get_attribute("href") is None


def test_links_that_lead_somewhere_are_left_alone(page, live_server):
    """The other half of the marking: a check that dulls every link is as
    broken as one that dulls none. The folder link is the interesting case --
    /api/preview 404s on a directory, so an existence check built on that
    endpoint would call a perfectly good folder link dead."""
    open_path(page, live_server, "links.md")
    # The marking is asynchronous, so the absence of a class proves nothing
    # until the check that would have added it has run.
    page.locator(".markdown-body a.broken").wait_for()
    live = page.locator('.markdown-body a[href="#/browse/100%25.md"]')
    assert live.count() == 1
    assert "broken" not in (live.get_attribute("class") or "")
    folder = page.locator('.markdown-body a[href="#/browse/notes"]')
    assert folder.count() == 1
    assert "broken" not in (folder.get_attribute("class") or "")


def test_a_broken_link_reads_as_dead_before_it_is_clicked(page, live_server):
    """A no-op the reader cannot see coming is indistinguishable from a page
    that has frozen. The class is only half the fix; the rule that renders it
    is the half the reader actually meets.

    The hover state is asserted alongside the resting one because `a:hover`
    matches an anchor with no href just as readily as a real link, and the
    global `a:hover { text-decoration: underline }` above would otherwise put
    an underline back on the moment the pointer arrives.
    """
    open_path(page, live_server, "links.md")
    dead = page.locator(".markdown-body a.broken")
    dead.wait_for()
    resting = dead.evaluate("el => getComputedStyle(el).textDecorationLine")
    assert resting == "line-through"
    dead.hover()
    assert dead.evaluate("el => getComputedStyle(el).textDecorationLine") == "line-through"
    live = page.locator('.markdown-body a[href="#/browse/notes"]')
    assert dead.evaluate("el => getComputedStyle(el).color") != live.evaluate(
        "el => getComputedStyle(el).color"
    )


def test_clicking_a_broken_link_stays_on_the_document(page, live_server):
    """The whole point: the old behaviour navigated, 404ed, and replaced the
    document with an error card under a changed URL, so the reader lost their
    place and had to press Back.

    Recording every hash the page visits, rather than only comparing the URL
    afterwards, is deliberate -- see the same pattern in test_navigation.py's
    inert-gesture test. A regression that navigated and then bounced back
    would leave the final URL right and the document restored, and only the
    recording can tell that apart from never having moved.
    """
    open_path(page, live_server, "links.md")
    page.locator(".markdown-body a.broken").wait_for()
    page.evaluate(
        "() => { "
        "window.__hashes = []; "
        "window.addEventListener('hashchange', () => window.__hashes.push(location.hash)); "
        "}"
    )
    before = page.evaluate("location.hash")
    page.locator(".markdown-body a.broken").click()
    # Nothing to wait_for_selector on for "stayed put": give a navigation
    # that should never happen a window in which to have happened.
    page.wait_for_timeout(400)
    assert page.evaluate("window.__hashes") == []
    assert page.evaluate("location.hash") == before
    assert page.locator("#content .error").count() == 0
    assert "Links" in page.locator(".markdown-body").inner_text()


def test_markdown_strips_inline_event_handlers(page, live_server):
    """Untrusted file content must not execute on render."""
    open_path(page, live_server, "hostile.md")
    page.wait_for_selector(".markdown-body")
    assert page.evaluate("() => window.__pwned") is None
    assert page.locator(".markdown-body img[onerror]").count() == 0


def test_markdown_neutralises_javascript_hrefs(page, live_server):
    """rewriteLinks deliberately leaves absolute schemes alone; the sanitizer removes this one."""
    open_path(page, live_server, "hostile.md")
    page.wait_for_selector(".markdown-body")
    hrefs = page.eval_on_selector_all(
        ".markdown-body a", "els => els.map(e => e.getAttribute('href'))"
    )
    assert not any(h and h.lower().startswith("javascript:") for h in hrefs)


def test_code_is_syntax_highlighted(page, live_server):
    open_path(page, live_server, "code.py")
    page.wait_for_selector("pre.code code.hljs")
    assert "return" in page.locator("pre.code").inner_text()


def test_tex_is_highlighted_not_just_monospaced(page, live_server):
    """The vendored common hljs build omits latex; 370 .tex files depend on it."""
    open_path(page, live_server, "paper.tex")
    page.wait_for_selector("pre.code code.hljs")
    assert (
        page.locator(
            "pre.code .hljs-keyword, pre.code .hljs-tag, pre.code span[class^='hljs-']"
        ).count()
        > 0
    )


def test_toml_is_highlighted_via_the_ini_grammar(page, live_server):
    """highlight.js registers no "toml" name; TOML is handled by the ini grammar."""
    open_path(page, live_server, "config.toml")
    page.wait_for_selector("pre.code code.hljs")
    assert page.locator("pre.code span[class^='hljs-']").count() > 0
    # The line above alone does not discriminate a correct "ini" mapping from
    # a broken one: hljs falls back to its own auto-detection for an
    # unrecognised language class, and for this ini-shaped content it happens
    # to guess "ini" anyway. code.js sets the code element's class from the
    # backend's declared language before hljs ever runs, and hljs's
    # auto-detect augments that class rather than replacing it -- so the
    # class name still tells the two cases apart.
    code_class = page.locator("pre.code code").get_attribute("class")
    assert "language-ini" in code_class
    assert "language-toml" not in code_class


def test_notebook_renders_cells_and_outputs(page, live_server):
    open_path(page, live_server, "nb.ipynb")
    page.wait_for_selector(".notebook-body")
    body = page.locator(".notebook-body").inner_text()
    assert "Notebook Heading" in body
    assert "notebook output" in body


def test_notebook_code_cells_are_coloured(page, live_server):
    """nbconvert emits Pygments markup but no stylesheet; without it, cells are monochrome."""
    open_path(page, live_server, "nb.ipynb")
    page.wait_for_selector(".notebook-body .highlight")
    coloured = page.evaluate(
        """() => {
            const el = document.querySelector('.notebook-body .highlight span[class]');
            if (!el) return null;
            return getComputedStyle(el).color;
        }"""
    )
    assert coloured is not None, "no Pygments span found — template output changed"
    assert coloured != "rgb(31, 35, 40)", "span inherits body colour: pygments.css is not applied"


def test_pdf_reader_uses_the_native_viewer_without_its_toolbar(page, live_server):
    open_path(page, live_server, "doc.pdf")
    frame = page.locator("iframe.pdf")
    frame.wait_for()
    assert frame.count() == 1
    assert page.locator(".pdf-shell").count() == 1
    assert "doc.pdf" in page.locator(".pdf-reader-title").inner_text()
    assert page.get_by_role("link", name="Download").count() == 0
    assert "doc.pdf" in frame.get_attribute("src")
    assert "toolbar=0" in frame.get_attribute("src")
    assert "navpanes=0" in frame.get_attribute("src")
    assert page.locator(".pdf-page canvas").count() == 0


def test_pdf_selection_is_left_to_the_native_viewer(page, live_server):
    open_path(page, live_server, "doc.pdf")
    page.wait_for_selector("iframe.pdf")
    assert page.locator(".pdf-select-layer").count() == 0
    assert page.locator(".pdf-text-line").count() == 0
    assert page.locator(".pdf-text-layer span").count() == 0


def test_pdf_viewer_fills_the_reading_pane(page, live_server):
    """Catches a regression back to the old bare iframe, which left the
    browser PDF viewer floating inside the normal document padding instead of
    occupying the available reading pane."""
    page.set_viewport_size({"width": 1400, "height": 900})
    open_path(page, live_server, "doc.pdf")
    shell = page.locator(".pdf-shell")
    frame = page.locator("iframe.pdf")
    shell.wait_for()

    shell_box = shell.bounding_box()
    frame_box = frame.bounding_box()
    main_box = page.locator("#main").bounding_box()

    assert shell_box["width"] >= main_box["width"] - 50
    assert shell_box["height"] >= 760
    assert abs(frame_box["width"] - shell_box["width"]) <= 2
    assert frame_box["height"] < shell_box["height"]
    assert shell.evaluate("el => getComputedStyle(el).borderTopStyle") == "solid"
    assert shell.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"


def test_pdf_pages_scroll_inside_the_reader_not_the_page(page, live_server):
    page.set_viewport_size({"width": 1000, "height": 520})
    open_path(page, live_server, "doc.pdf")
    page.wait_for_selector("iframe.pdf")
    main = page.locator("#main")
    frame = page.locator("iframe.pdf")

    assert main.evaluate("el => getComputedStyle(el).overflowY") == "hidden"
    assert main.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
    assert frame.bounding_box()["height"] > 300


def test_table_shows_schema_and_first_page(page, live_server):
    open_path(page, live_server, "data.parquet")
    page.wait_for_selector(".datatable")
    assert "250 rows" in page.locator(".card-head").inner_text()
    assert page.locator(".datatable tr").count() == 101  # header + 100 rows


def test_table_pager_advances(page, live_server):
    open_path(page, live_server, "data.parquet")
    page.wait_for_selector(".datatable")
    assert page.locator(".datatable tr").nth(1).inner_text().startswith("0")
    page.get_by_role("button", name="Next").click()
    # Optional chaining, not a bare property read: the click triggers a full
    # re-render (container.replaceChildren() then an async fetch), so .pager
    # briefly does not exist. A bare `.textContent` throws during that gap,
    # and Playwright's wait_for_function does not retry past a thrown
    # exception -- it fails on the very first evaluation instead of polling.
    page.wait_for_function(
        "() => document.querySelector('.pager span')?.textContent?.includes('Page 2')"
    )
    assert page.locator(".datatable tr").nth(1).inner_text().startswith("100")


def test_table_previous_is_disabled_on_the_first_page(page, live_server):
    open_path(page, live_server, "data.parquet")
    page.wait_for_selector(".pager")
    assert page.get_by_role("button", name="Previous").is_disabled()


def test_unsupported_type_offers_a_download(page, live_server):
    open_path(page, live_server, "blob.dat")
    assert "No preview" in page.locator("#content").inner_text()
    assert page.get_by_role("link", name="Download").count() == 1


def test_status_bar_reports_type_size_and_age(page, live_server):
    open_path(page, live_server, "code.py")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('·')")
    status = page.locator("#status").inner_text()
    assert "python" in status
    assert "B" in status
    assert "modified" in status


def test_no_console_errors_across_every_renderer(page, live_server):
    # Chromium's console message text for a failed resource load is a fixed,
    # generic string -- "Failed to load resource: the server responded with a
    # status of 404 (Not Found)" -- with no URL in it at all. The failing
    # request's URL only shows up on the message's `location`. A substring
    # check against `.text` therefore cannot discriminate one URL's 404 from
    # another's; it can only match "404" itself, which swallows every 404.
    errors = []
    page.on(
        "console",
        lambda m: errors.append((m.text, m.location.get("url", ""))) if m.type == "error" else None,
    )
    page.on("pageerror", lambda e: errors.append((str(e), "")))
    for path in ["", "notes", "README.md", "code.py", "nb.ipynb", "data.parquet", "blob.dat"]:
        open_path(page, live_server, path)
    page.wait_for_load_state("networkidle")
    # renderPreview deliberately probes /api/preview on "notes" (a directory)
    # and catches its 404 to fall back to /api/tree -- that is the single
    # expected, handled 404 among the paths opened above ("" is the root and
    # goes straight to /api/tree, never hitting /api/preview at all). Matching
    # the specific failing URL, rather than the shared substring "404", means
    # any other 404 -- a missing pygments.css, a mistyped <script src>, a
    # dropped vendored asset -- still fails the test instead of being
    # swallowed alongside the deliberate one.
    errors = [(text, url) for text, url in errors if "/api/preview?path=notes" not in url]
    assert errors == []


def test_mermaid_renders_in_a_crlf_document(page, live_server):
    """CRLF is the common case on Windows, and an `\n`-anchored fence regex misses it."""
    open_path(page, live_server, "crlf.md")
    page.wait_for_selector(".mermaid-slot svg", timeout=10000)
    assert page.locator(".mermaid-slot svg").count() == 1


def test_katex_renders_in_a_crlf_document(page, live_server):
    """Same document, same maths -- guards against a line-ending fix breaking KaTeX."""
    open_path(page, live_server, "crlf.md")
    page.wait_for_selector(".katex", timeout=10000)
    assert page.locator(".katex").count() >= 2
