# armoire

Serve any folder as a local, read-only website.

A folder that accumulates hundreds of documents becomes unbrowsable. File managers
show names and nothing else; opening a notebook or a parquet file means launching a
separate tool; relative links between READMEs are dead. armoire renders the folder
in a browser — markdown with maths and diagrams, PDFs, notebooks with their outputs,
and parquet/CSV as paginated tables.

## Install

Not on PyPI yet, so install from the repository. This puts `armoire` on your PATH
and can be run from any directory:

```console
$ uv tool install --from git+https://github.com/dafu-zhu/armoire armoire
$ armoire serve /path/to/folder
```

If `armoire` is not found afterwards, run `uv tool update-shell` and restart your
terminal. Upgrade later with `uv tool upgrade armoire`.

To run it once without installing anything:

```console
$ uvx --from git+https://github.com/dafu-zhu/armoire armoire serve .
```

## Use

```console
$ armoire serve .                 # browse at http://127.0.0.1:8420
$ armoire serve ~/notes -dp 9000  # background, on port 9000
$ armoire list                    # which port is serving which folder
```

Open the URL it prints. The left rail is a lazy directory tree; the box at the top
filters every file in the folder by fuzzy match. Each file's URL is bookmarkable —
`#/browse/research/0dte/README.md` — and the back button works.

One process serves one folder, so several folders means several ports. `-d`
runs a server in the background so it does not need a terminal of its own, and
`armoire list` reports which port is serving what.

A port already held by another armoire is refused rather than taken; `-f`
replaces that instance, and `-df` replaces it and detaches. A port held by
anything that is *not* armoire is always refused -- armoire stops only processes
it can identify as its own, and `-f` does not change that.

| File type | What you get |
|---|---|
| Markdown | Rendered, with KaTeX maths, Mermaid diagrams, and relative links that navigate in-app |
| PDF | Embedded in the browser's own viewer |
| Notebooks | Cells and outputs, including plots, without a Jupyter server |
| Code | Syntax highlighted — Python, LaTeX, Julia, MATLAB, R, SQL and ~35 more |
| Parquet / CSV | Schema, row count, and paginated rows. A 363 MB file opens in under a second |
| Anything else | Size and a download link |

A directory shows its file listing, then renders its `README.md` underneath, the way
GitHub does.

Large folders take a moment to index — roughly three seconds for 190,000 files. The
tree works immediately; the filter box says `Indexing…` until it is ready.

### What it will not do

`serve` never writes to the folder — not even the registry, which lives outside
it (see [Status](#status) below). Not by convention — there is a test that
snapshots every file's checksum before and after exercising every endpoint.

It binds `127.0.0.1` only, with no option to change that, because it streams file
contents from the folder you point it at. Nothing is reachable from your network.

Ignored everywhere: `.git`, `.venv`, `node_modules`, `__pycache__`, `site-packages`,
`.ruff_cache`, `.pytest_cache`.

## Status

Two screens. The roadmap shows your projects and what blocks what, drawn from a
registry you write; the viewer renders any file you click through to. Without a
registry, armoire opens straight into the file browser.

    [[project]]
    name = "0DTE"
    paths = ["research/0dte"]
    blocked_by = ["FINM 320", "FINM 330"]
    category = "research"
    status = "active"
    due = 2026-08-17

Every project must declare `blocked_by`, `category`, or both — one with neither
has nowhere on screen to go and is reported as a registry issue. `status` is one
of `not-started`, `active`, `paused`, `done`; it defaults to `not-started`, and an
unrecognised value falls back to `not-started` as a registry issue rather than
dropping the project from the graph. Edit it from the roadmap by clicking the
chip in a node's corner, or by hand in the registry file.

See the [roadmap design](docs/superpowers/specs/2026-08-01-armoire-roadmap-design.md)
and the [Phase 3 design](docs/superpowers/specs/2026-08-02-armoire-phase3-design.md)
for the full field list and how category placement and status work.

### The registry lives outside the folder

The registry is not a file inside the folder you serve. armoire keeps it, and
everything else it writes, in a per-user store — so describing a folder never
means modifying it:

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\armoire` |
| macOS | `~/Library/Application Support/armoire` |
| Linux | `$XDG_CONFIG_HOME/armoire`, falling back to `~/.config/armoire` |

Inside it, every folder armoire has served gets its own directory:

```
<store>/folders/<basename>-<first 8 hex of sha256 of the resolved path>/
    registry.toml    the projects, the dependency edges — the file you edit
    state.json       project status, written when you click a chip
```

The basename is there so the directory is recognisable to a human reading the
store; the hash is what makes it unique. Two folders called `docs` in different
places therefore get two directories rather than sharing one, and renaming a
folder gives it a fresh directory instead of picking up the old one's registry.
The path is resolved through symlinks and case-normalised on Windows first, so
two spellings of one folder do not get two stores.

`serve` creates a commented registry stub the first time it serves a folder, and
prints the path so you know where to edit it. If the folder already carries a
Phase 2 `armoire.toml`, that file is copied into the store — never deleted,
since deleting it would itself be a write to the served folder — and the
startup output says which copy is now authoritative.

The roadmap and the file browser both carry an **Edit registry** button in the
footer, and the box that reports a registry parse error carries one too, so
the fix is one click from wherever the failure shows up. Either opens the
file in whatever application your system associates with `.toml`, or gives
you the path instead if nothing is.

If the store would land inside the folder being served (a home directory, or
`%APPDATA%` itself), armoire refuses to write anything there and serves
read-only instead, saying why — and with no writable store there is no
registry to open, so the button is absent everywhere.

Project status lives per folder in the store, not in the browser, so it follows
the folder rather than a browser tab and survives clearing site data. Node
positions and the tree divider's width are the opposite: view preferences tied
to one browser, so they stay in `localStorage` as before.

## Developing

```console
$ git clone https://github.com/dafu-zhu/armoire
$ cd armoire
$ uv sync
$ uv run playwright install chromium     # for the browser tests
$ uv run pytest
$ uv run armoire serve /path/to/folder
```

Frontend libraries are vendored under `src/armoire/static/vendor/` and committed, so
the wheel is self-contained and the page makes no external requests. Re-run
`uv run python scripts/vendor.py` only to bump a version.

## License

MIT
