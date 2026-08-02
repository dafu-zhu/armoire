import json

import pytest

from armoire.previews.notebook import preview_notebook


@pytest.fixture
def notebook(tmp_path):
    path = tmp_path / "n.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "markdown",
                        "id": "intro",
                        "metadata": {},
                        "source": ["# Heading\n"],
                    },
                    {
                        "cell_type": "code",
                        "id": "greet",
                        "execution_count": 1,
                        "metadata": {},
                        "source": ["print('hello')\n"],
                        "outputs": [
                            {
                                "output_type": "stream",
                                "name": "stdout",
                                "text": ["hello\n"],
                            }
                        ],
                    },
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_returns_notebook_kind(notebook):
    assert preview_notebook(notebook)["kind"] == "notebook"


def test_renders_markdown_cells(notebook):
    html = preview_notebook(notebook)["html"]
    # Markdown cell rendered: "# Heading" becomes <h1> element
    assert "<h1" in html
    # Negative control: raw markdown source is not in the HTML
    assert "# Heading" not in html


def test_renders_code_cells(notebook):
    html = preview_notebook(notebook)["html"]
    # Code highlighted: syntax highlighting creates <span> tags with class attributes
    # This structure cannot appear in raw JSON source
    assert "<span class=" in html
    # Negative control: raw source code is not passed through
    assert "print('hello')" not in html


def test_renders_cell_outputs(notebook):
    html = preview_notebook(notebook)["html"]
    # Output rendered into document structure: output_stream class marks stream output
    assert "output_stream" in html
    # Negative control: output structure would not exist in raw JSON
    assert "output_stdout" in html


def test_output_is_a_fragment_not_a_full_document(notebook):
    html = preview_notebook(notebook)["html"]
    # Fragment, not full document: no html/head/body/doctype tags
    assert "<!DOCTYPE" not in html.upper()
    assert "<html" not in html.lower()
    assert "<head" not in html.lower()
    assert "<body" not in html.lower()


def test_corrupt_notebook_raises_valueerror(tmp_path):
    bad = tmp_path / "bad.ipynb"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        preview_notebook(bad)
