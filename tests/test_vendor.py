"""Vendored asset completeness: does every face a stylesheet references exist?

Separate from test_shell.py because this checks files on disk directly and
needs neither a browser nor a live server.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "armoire" / "static"


def test_every_katex_font_referenced_by_the_stylesheet_is_vendored():
    """A missing face does not fail loudly — the maths silently loses its font."""
    css = (STATIC / "vendor" / "katex.css").read_text(encoding="utf-8")
    referenced = sorted(set(re.findall(r"url\((fonts/[^)]+\.woff2)\)", css)))
    assert referenced, "no woff2 faces found — the regex or the stylesheet changed"
    missing = [f for f in referenced if not (STATIC / "vendor" / f).is_file()]
    assert missing == []


def test_dagre_is_vendored():
    assert (STATIC / "vendor" / "dagre.js").is_file()


def test_dagre_is_loaded_before_the_module_entry_point():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/vendor/dagre.js" in html
    assert html.index("/vendor/dagre.js") < html.index('src="/app.js?v=2"')


def test_the_roadmap_has_exactly_one_visibility_mechanism():
    """`hidden` is display:none !important, so a second CSS switch cannot
    override it. Two switches invite an edit that toggles only one."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "data-active" not in css
