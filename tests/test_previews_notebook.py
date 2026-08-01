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
                        "metadata": {},
                        "source": ["# Heading\n"],
                    },
                    {
                        "cell_type": "code",
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
    assert "Heading" in preview_notebook(notebook)["html"]


def test_renders_code_cells(notebook):
    assert "print" in preview_notebook(notebook)["html"]


def test_renders_cell_outputs(notebook):
    assert "hello" in preview_notebook(notebook)["html"]


def test_output_is_a_fragment_not_a_full_document(notebook):
    html = preview_notebook(notebook)["html"]
    assert "<!DOCTYPE" not in html.upper()


def test_corrupt_notebook_raises_valueerror(tmp_path):
    bad = tmp_path / "bad.ipynb"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        preview_notebook(bad)
