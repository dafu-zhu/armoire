"""Markdown and source files: hand the raw text to the client and let it render."""

from pathlib import Path

from armoire.previews import LANGUAGES

MAX_BYTES = 2_000_000


def preview_text(path: Path, kind: str) -> dict:
    ext = path.suffix.removeprefix(".").lower()
    # errors="replace" because a mislabelled .txt should show its readable parts
    # rather than fail the whole preview.
    text = path.read_bytes()[:MAX_BYTES].decode("utf-8", errors="replace")
    # Normalize CRLF to LF for cross-platform consistency
    text = text.replace("\r\n", "\n")
    language = "markdown" if kind == "markdown" else LANGUAGES.get(ext, "plaintext")
    return {"kind": kind, "text": text, "language": language}
