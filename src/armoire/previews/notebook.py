"""Notebooks rendered read-only, outputs included.

The "basic" nbconvert template emits an HTML fragment rather than a full
document, which is what we want since it is injected into an existing page.
"""

from pathlib import Path

import nbformat
from nbconvert import HTMLExporter


def preview_notebook(path: Path) -> dict:
    try:
        nb = nbformat.read(path, as_version=4)
    except Exception as exc:
        # nbformat raises several unrelated types for a malformed file.
        # Callers only need to know it was unreadable.
        raise ValueError(f"could not read notebook: {exc}") from exc

    exporter = HTMLExporter(template_name="basic")
    body, _resources = exporter.from_notebook_node(nb)
    return {"kind": "notebook", "html": body}
