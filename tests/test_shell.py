"""The page shell: does it load, and does it match the spec's visual tokens."""

import pytest

REQUIRED_IDS = [
    "tree",
    "filter",
    "filter-results",
    "breadcrumb",
    "content",
    "status",
    "open-native",
]


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_shell_provides_the_dom_contract(page, live_server, element_id):
    page.goto(live_server)
    assert page.locator(f"#{element_id}").count() == 1


def test_page_makes_no_external_requests(page, live_server):
    external = []
    page.on(
        "request",
        lambda request: (
            external.append(request.url) if not request.url.startswith(live_server) else None
        ),
    )
    page.goto(live_server)
    page.wait_for_load_state("networkidle")
    # A page that failed to load also makes zero external requests, so that
    # alone would prove nothing. Confirm the shell actually rendered first.
    assert page.locator("#tree").count() == 1
    assert external == []


def test_background_and_text_use_the_specified_colours(page, live_server):
    page.goto(live_server)
    body = page.locator("body")
    assert body.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
    assert body.evaluate("el => getComputedStyle(el).color") == "rgb(31, 35, 40)"


def test_filter_input_is_present_and_empty(page, live_server):
    page.goto(live_server)
    assert page.locator("#filter").input_value() == ""
    assert page.locator("#filter-results").is_hidden()
