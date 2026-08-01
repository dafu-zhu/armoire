import pytest

from armoire.previews import kind_for
from armoire.previews.text import preview_text


@pytest.mark.parametrize(
    ("ext", "expected"),
    [
        ("md", "markdown"),
        ("markdown", "markdown"),
        ("py", "code"),
        ("tex", "code"),
        ("json", "code"),
        ("txt", "code"),
        ("ipynb", "notebook"),
        ("parquet", "table"),
        ("csv", "table"),
        ("pdf", "pdf"),
        ("png", "image"),
        ("jpg", "image"),
        ("dat", "binary"),
        ("", "binary"),
    ],
)
def test_kind_for_extension(ext, expected):
    assert kind_for(ext) == expected


def test_markdown_preview_returns_raw_text(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Title\n", encoding="utf-8")
    assert preview_text(f, "markdown") == {
        "kind": "markdown",
        "text": "# Title\n",
        "language": "markdown",
    }


def test_code_preview_reports_language(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert preview_text(f, "code")["language"] == "python"


def test_unknown_code_extension_falls_back_to_plaintext(tmp_path):
    f = tmp_path / "a.conf"
    f.write_text("k=v\n", encoding="utf-8")
    assert preview_text(f, "code")["language"] == "plaintext"


def test_undecodable_bytes_do_not_raise(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"ok \xff\xfe bad")
    assert "ok" in preview_text(f, "code")["text"]
