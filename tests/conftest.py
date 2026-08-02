"""A small sample folder, and a live server in front of it."""

import json
import socket
import threading
import time

import polars as pl
import pytest
import uvicorn

from armoire.app import create_app

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""

ROOT_README = """# Sample Folder

Inline math $E = mc^2$ and a display equation:

$$\\int_0^1 x^2 dx = \\frac{1}{3}$$

```mermaid
flowchart LR
  A[Start] --> B[End]
```

See [notes/](notes/) for the nested folder.
"""

# Every cell carries an "id": nbformat_minor 5 requires it, and a fixture
# without one is not shaped like anything Jupyter would actually write.
NOTEBOOK = {
    "cells": [
        {
            "cell_type": "markdown",
            "id": "intro",
            "metadata": {},
            "source": ["# Notebook Heading\n"],
        },
        {
            "cell_type": "code",
            "id": "emit",
            "execution_count": 1,
            "metadata": {},
            "source": ["print('notebook output')\n"],
            "outputs": [{"output_type": "stream", "name": "stdout", "text": ["notebook output\n"]}],
        },
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}


@pytest.fixture(scope="session")
def sample_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("sample")
    # newline="" avoids Windows' universal-newline translation on write, so
    # the markdown renderer's exact `\n`-anchored mermaid-fence regex sees
    # the same bytes on every platform.
    (root / "README.md").write_text(ROOT_README, encoding="utf-8", newline="")
    # The same document with CRLF endings. Windows editors and git's autocrlf
    # produce these routinely -- 8 of the 11 mermaid documents in the folder
    # armoire was built for are CRLF -- so the renderer must handle both.
    (root / "crlf.md").write_bytes(ROOT_README.replace("\n", "\r\n").encode("utf-8"))
    (root / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="")
    (root / "doc.pdf").write_bytes(MINIMAL_PDF)
    (root / "blob.dat").write_bytes(b"\x00\x01\x02\x03")
    (root / "nb.ipynb").write_text(json.dumps(NOTEBOOK), encoding="utf-8", newline="")
    (root / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n"
        "Some text.\n\\end{document}\n",
        encoding="utf-8",
        newline="",
    )
    (root / "config.toml").write_text('[section]\nkey = "value"\n', encoding="utf-8", newline="")
    (root / "hostile.md").write_text(
        "# Hostile\n\n"
        '<img src=x onerror="window.__pwned = true">\n\n'
        # No spaces in the destination: marked's CommonMark-compliant link
        # parser rejects an unenclosed space in a link destination and never
        # emits an <a> tag at all for one, which would make this vector
        # untestable for reasons that have nothing to do with the sanitizer.
        "[click me](javascript:window.__pwned=true)\n",
        encoding="utf-8",
        newline="",
    )
    pl.DataFrame({"i": range(250), "label": [f"r{n}" for n in range(250)]}).write_parquet(
        root / "data.parquet"
    )
    # "%" is not a valid percent-escape by itself; decodeURIComponent throws
    # on it unless every write to location.hash first encodes the segment.
    (root / "50% off.md").write_text(
        "# Percent\n\nA name with a literal percent sign.\n", encoding="utf-8", newline=""
    )
    # rewriteLinks (renderers/markdown.js) is a third hash-write site, distinct
    # from navigate() and the breadcrumb: a relative link to a percent-named
    # file must round-trip through the same encoding as the other two. Named
    # "100%.md" rather than reusing "50% off.md" -- marked itself partially
    # encodes a raw space in a link destination (leaves "%" untouched but
    # turns " " into "%20"), which would confound this test with marked's own
    # quirk rather than isolating rewriteLinks's. A bare "%" with no adjacent
    # space passes through marked unmodified, verified empirically.
    (root / "100%.md").write_text(
        "# Percent Only\n\nA name with a literal percent sign and no space.\n",
        encoding="utf-8",
        newline="",
    )
    (root / "links.md").write_text("# Links\n\n[percent](100%.md)\n", encoding="utf-8", newline="")

    notes = root / "notes"
    notes.mkdir()
    (notes / "README.md").write_text(
        "# Notes\n\nNested folder readme.\n", encoding="utf-8", newline=""
    )
    (notes / "deep").mkdir()
    (notes / "deep" / "buried.md").write_text("# Buried\n", encoding="utf-8", newline="")

    ignored = root / ".venv"
    ignored.mkdir()
    (ignored / "junk.py").write_text("noise\n", encoding="utf-8", newline="")
    return root


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(sample_root):
    app = create_app(sample_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start within 10s")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
