"""Extension to preview kind. The client switches on `kind`, never on extension."""

from pathlib import Path

MARKDOWN_EXTS = frozenset({"md", "markdown"})
NOTEBOOK_EXTS = frozenset({"ipynb"})
TABLE_EXTS = frozenset({"parquet", "csv"})
PDF_EXTS = frozenset({"pdf"})
IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp"})
CODE_EXTS = frozenset(
    {
        "py",
        "tex",
        "bib",
        "json",
        "toml",
        "yaml",
        "yml",
        "txt",
        "js",
        "ts",
        "html",
        "css",
        "sh",
        "sql",
        "r",
        "cpp",
        "c",
        "h",
        "hpp",
        "rs",
        "go",
        "java",
        "jl",
        "m",
        "ini",
        "cfg",
        "conf",
        "gitignore",
        "gitattributes",
        "gitmodules",
        "editorconfig",
        "env",
        "python-version",
    }
)

LANGUAGES = {
    "py": "python",
    "tex": "latex",
    "bib": "bibtex",
    "json": "json",
    "toml": "toml",
    "yaml": "yaml",
    "yml": "yaml",
    "js": "javascript",
    "ts": "typescript",
    "html": "xml",
    "css": "css",
    "sh": "bash",
    "sql": "sql",
    "r": "r",
    "cpp": "cpp",
    "c": "c",
    "h": "c",
    "hpp": "cpp",
    "rs": "rust",
    "go": "go",
    "java": "java",
    "jl": "julia",
    "m": "matlab",
    "ini": "ini",
    "cfg": "ini",
    "conf": "ini",
}


def extension_of(path: Path) -> str:
    """The extension used for dispatch: no leading dot, lowercased.

    Dotfiles are the reason this is not just `path.suffix`. Path(".gitignore")
    has an empty suffix, so dispatching on suffix alone renders every dotfile
    as an unpreviewable binary.
    """
    if path.suffix:
        return path.suffix.removeprefix(".").lower()
    if path.name.startswith("."):
        return path.name.removeprefix(".").lower()
    return ""


def kind_for(ext: str) -> str:
    if ext in MARKDOWN_EXTS:
        return "markdown"
    if ext in NOTEBOOK_EXTS:
        return "notebook"
    if ext in TABLE_EXTS:
        return "table"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in CODE_EXTS:
        return "code"
    return "binary"
