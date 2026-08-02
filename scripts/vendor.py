"""Download the frontend libraries into the package.

Vendored rather than CDN-loaded so armoire works offline and makes no network
request per page load. The downloaded files are COMMITTED to the repository:
the wheel has to be self-contained or `uvx armoire serve` installs a broken
page. Re-run this only to bump a version.
"""

import re
import urllib.request
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "src" / "armoire" / "static" / "vendor"

FILES = {
    "marked.js": "https://cdn.jsdelivr.net/npm/marked@14.1.3/marked.min.js",
    "katex.js": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js",
    "katex.css": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css",
    "katex-auto-render.js": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js",
    "mermaid.js": "https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.min.js",
    "highlight.js": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.10.0/highlight.min.js",
    "highlight.css": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.10.0/styles/github.min.css",
    # The "common" build above omits these three languages that armoire's own
    # LANGUAGES map routes .tex/.jl/.m files to. Fetched separately and loaded
    # after highlight.js in index.html, since each registers itself against
    # the global hljs rather than exporting anything.
    "hljs-latex.js": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.10.0/languages/latex.min.js",
    "hljs-julia.js": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.10.0/languages/julia.min.js",
    "hljs-matlab.js": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.10.0/languages/matlab.min.js",
    "purify.js": "https://cdn.jsdelivr.net/npm/dompurify@3.1.7/dist/purify.min.js",
    "dagre.js": "https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js",
}

FONTS_BASE = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/"


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {dest.name}")
    with urllib.request.urlopen(url) as response:
        dest.write_bytes(response.read())


def fetch_katex_fonts() -> int:
    """Download every woff2 face katex.css actually references.

    Derived from the stylesheet rather than hardcoded: a hand-maintained list
    silently drifts, and a missing face does not fail — the maths just renders
    in a fallback font. Only .woff2 is fetched: every browser that can run
    this app supports it, and the .woff/.ttf fallbacks the stylesheet also
    lists would triple the font payload for no benefit.
    """
    css = (VENDOR / "katex.css").read_text(encoding="utf-8")
    faces = sorted(set(re.findall(r"url\((fonts/[^)]+\.woff2)\)", css)))
    for face in faces:
        fetch(FONTS_BASE + face, VENDOR / face)
    return len(faces)


def write_pygments_css() -> int:
    """nbconvert's basic template emits Pygments markup but no stylesheet.

    Generated from the installed Pygments rather than downloaded: it then
    matches whatever version nbconvert actually renders with.
    """
    from pygments.formatters import HtmlFormatter

    css = HtmlFormatter(style="default").get_style_defs(".highlight")
    dest = VENDOR / "pygments.css"
    dest.write_text(css, encoding="utf-8")
    return len(css)


def main() -> None:
    print(f"vendoring into {VENDOR}")
    for name, url in FILES.items():
        fetch(url, VENDOR / name)
    count = fetch_katex_fonts()
    print(f"vendored {count} KaTeX font faces")
    size = write_pygments_css()
    print(f"generated pygments.css ({size} bytes)")
    print("done")


if __name__ == "__main__":
    main()
