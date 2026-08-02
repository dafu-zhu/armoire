from pathlib import Path

import pytest

from armoire.previews import extension_of, kind_for
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
    f.write_bytes(b"# Title\n")
    assert preview_text(f, "markdown") == {
        "kind": "markdown",
        "text": "# Title\n",
        "language": "markdown",
    }


def test_code_preview_reports_language(tmp_path):
    f = tmp_path / "a.py"
    f.write_bytes(b"x = 1\n")
    assert preview_text(f, "code")["language"] == "python"


def test_unknown_code_extension_falls_back_to_plaintext(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_bytes(b"k=v\n")
    assert preview_text(f, "code")["language"] == "plaintext"


def test_undecodable_bytes_do_not_raise(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"ok \xff\xfe bad")
    assert "ok" in preview_text(f, "code")["text"]


def test_large_file_read_is_bounded_by_max_bytes_not_just_the_response(tmp_path, monkeypatch):
    """MAX_BYTES must bound the *read*, not just the returned text:
    `read_bytes()[:MAX_BYTES]` allocates the whole file before truncating, so
    a multi-GB file in the served root is a multi-GB allocation per request.
    Lower MAX_BYTES and make read_bytes() explode if called -- the bounded
    handle.read() path must never touch it, and the truncated text must still
    be correct."""
    import armoire.previews.text as text_module

    def boom(self, *args, **kwargs):
        raise AssertionError("read_bytes() must not be called: it reads past MAX_BYTES")

    monkeypatch.setattr(Path, "read_bytes", boom)
    monkeypatch.setattr(text_module, "MAX_BYTES", 10)

    f = tmp_path / "big.txt"
    f.write_bytes(b"abcdefghij" * 100)  # 1000 bytes, far past the 10-byte bound
    result = preview_text(f, "code")
    assert result["text"] == "abcdefghij"


def test_preview_text_routes_dotfile_language_through_extension_of(tmp_path):
    """previews/__init__.py's extension_of exists specifically because
    path.suffix is empty for dotfiles. If text.py computed its own ext via
    path.suffix instead of extension_of, a file literally named ".py" would
    report language "plaintext" (path.suffix == "") instead of "python"."""
    f = tmp_path / ".py"
    f.write_bytes(b"x = 1\n")
    assert preview_text(f, "code")["language"] == "python"


def test_crlf_line_endings_are_preserved_verbatim(tmp_path):
    """A read-only viewer must not silently rewrite the bytes it displays."""
    f = tmp_path / "windows.md"
    f.write_bytes(b"line one\r\nline two\r\n")
    assert preview_text(f, "markdown")["text"] == "line one\r\nline two\r\n"


def test_conf_files_are_highlighted_as_ini(tmp_path):
    f = tmp_path / "app.conf"
    f.write_bytes(b"[section]\nkey = value\n")
    assert preview_text(f, "code")["language"] == "ini"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (".gitignore", "gitignore"),
        (".python-version", "python-version"),
        ("README.md", "md"),
        ("archive.TAR", "tar"),
        ("Makefile", ""),
        (".hidden.md", "md"),
    ],
)
def test_extension_of(name, expected):
    assert extension_of(Path(name)) == expected


@pytest.mark.parametrize("name", [".gitignore", ".gitattributes", ".python-version"])
def test_dotfiles_dispatch_as_code_not_binary(name):
    """Path.suffix is empty for these, so dispatching on suffix alone hid them."""
    assert kind_for(extension_of(Path(name))) == "code"
