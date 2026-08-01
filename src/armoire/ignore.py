"""Names that are never listed.

Matching is on the exact entry name, not a glob. These are the directories that
turn a browsable folder into a 189k-file one: four nested virtualenvs and their
site-packages accounted for the bulk of the originating case.
"""

DEFAULT_IGNORES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        "site-packages",
        ".ruff_cache",
        ".pytest_cache",
    }
)


def is_ignored(name: str, ignores: frozenset[str] = DEFAULT_IGNORES) -> bool:
    return name in ignores
