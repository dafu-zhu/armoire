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
$ armoire serve ~/notes --port 9000
```

Open the URL it prints. The left rail is a lazy directory tree; the box at the top
filters every file in the folder by fuzzy match. Each file's URL is bookmarkable —
`#/research/0dte/README.md` — and the back button works.

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

`serve` never writes to the folder. Not by convention — there is a test that
snapshots every file's checksum before and after exercising every endpoint.

It binds `127.0.0.1` only, with no option to change that, because it streams file
contents from the folder you point it at. Nothing is reachable from your network.

Ignored everywhere: `.git`, `.venv`, `node_modules`, `__pycache__`, `site-packages`,
`.ruff_cache`, `.pytest_cache`.

## Status

The viewer is complete and tested. Templates, scaffolding and conformance checking
are designed but not yet built — `armoire init` and `armoire check` do not exist
yet. See the [design spec](docs/superpowers/specs/2026-08-01-armoire-design.md) for
where it is going.

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
