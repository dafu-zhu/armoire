"""Markdown and source files: hand the raw text to the client and let it render."""

from pathlib import Path

from armoire.previews import LANGUAGES, extension_of

MAX_BYTES = 2_000_000


def preview_text(path: Path, kind: str) -> dict:
    ext = extension_of(path)
    # errors="replace" because a mislabelled .txt should show its readable parts
    # rather than fail the whole preview. Read with a bounded handle.read()
    # rather than read_bytes()[:MAX_BYTES] -- the latter allocates the whole
    # file before truncating, so a multi-GB file in the served root would be
    # a multi-GB allocation per request.
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES)
    text = raw.decode("utf-8", errors="replace")
    language = "markdown" if kind == "markdown" else LANGUAGES.get(ext, "plaintext")
    return {"kind": kind, "text": text, "language": language}
