"""Download the frontend libraries into the package.

Vendored rather than CDN-loaded so armoire works offline and makes no network
request per page load. The downloaded files are COMMITTED to the repository:
the wheel has to be self-contained or `uvx armoire serve` installs a broken
page. Re-run this only to bump a version.
"""

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
}

FONTS_BASE = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/"
FONTS = [
    "KaTeX_Main-Regular.woff2",
    "KaTeX_Main-Bold.woff2",
    "KaTeX_Main-Italic.woff2",
    "KaTeX_Math-Italic.woff2",
    "KaTeX_Size1-Regular.woff2",
    "KaTeX_Size2-Regular.woff2",
    "KaTeX_AMS-Regular.woff2",
]


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {dest.name}")
    with urllib.request.urlopen(url) as response:
        dest.write_bytes(response.read())


def main() -> None:
    print(f"vendoring into {VENDOR}")
    for name, url in FILES.items():
        fetch(url, VENDOR / name)
    for font in FONTS:
        fetch(FONTS_BASE + font, VENDOR / "fonts" / font)
    print("done")


if __name__ == "__main__":
    main()
