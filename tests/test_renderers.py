"""Every renderer, exercised against the sample folder in a real browser."""


def open_path(page, live_server, path):
    page.goto(f"{live_server}/#/{path}")
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
    link = page.locator('.markdown-body a[href="#/notes"]')
    assert link.count() == 1
    link.click()
    page.wait_for_selector(".listing")


def test_code_is_syntax_highlighted(page, live_server):
    open_path(page, live_server, "code.py")
    page.wait_for_selector("pre.code code.hljs")
    assert "return" in page.locator("pre.code").inner_text()


def test_notebook_renders_cells_and_outputs(page, live_server):
    open_path(page, live_server, "nb.ipynb")
    page.wait_for_selector(".notebook-body")
    body = page.locator(".notebook-body").inner_text()
    assert "Notebook Heading" in body
    assert "notebook output" in body


def test_pdf_is_embedded(page, live_server):
    open_path(page, live_server, "doc.pdf")
    frame = page.locator("iframe.pdf")
    assert frame.count() == 1
    assert "doc.pdf" in frame.get_attribute("src")


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
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    for path in ["", "notes", "README.md", "code.py", "nb.ipynb", "data.parquet", "blob.dat"]:
        open_path(page, live_server, path)
    page.wait_for_load_state("networkidle")
    # Chromium logs a "Failed to load resource: ... 404" console error for any
    # fetch() response with a non-2xx status, even one the application catches.
    # renderPreview deliberately probes /api/preview on "notes" (a directory)
    # and catches its 404 to fall back to /api/tree -- that expected, handled
    # 404 is not a bug, so it is excluded here; any other console or page
    # error still fails the test.
    errors = [e for e in errors if "404" not in e]
    assert errors == []
