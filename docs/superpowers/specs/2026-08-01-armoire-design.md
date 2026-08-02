# armoire — design

**Date:** 2026-08-01
**Status:** Phase 1 shipped. The template/scaffolding/conformance design below is
**superseded** by [`2026-08-01-armoire-roadmap-design.md`](2026-08-01-armoire-roadmap-design.md),
which replaces it with a project roadmap. It was written before the viewer
existed and guessed at a need that turned out to be different. The Phase 1
sections — viewer, previews, path jail, read-only boundary — remain current and
describe what shipped.

## Problem

A folder that accumulates hundreds of documents becomes unbrowsable. The originating
case is `D:\GitHub\summer-26`: 610 markdown, 521 PDF, 370 TeX, 213 notebooks, 1202
Python, 4456 parquet, 109 CSV — 12 GB across 189k files once four nested `.venv`
trees are counted. Explorer shows names and nothing else. Opening a notebook or a
parquet file means launching a separate tool. Relative links between READMEs are
dead. Nothing enforces the conventions the folders are supposed to follow, so
sibling projects drift apart in structure.

armoire serves any such folder as a local website: browse the tree, read the files
in place, and check the folder against a declared structure.

## Scope

**In:** browse and preview, structure templates, scaffolding, conformance checking.

**Out:** full-text search, editing, git decoration, project dashboards, auth,
multi-root, dark theme.

## Distribution

Public repo `dafu-zhu/armoire`, MIT. Install-free entry via `uvx armoire serve .`.
CI runs ruff and pytest on Python 3.11–3.13; PyPI publish on tag. Cross-platform —
`pathlib` throughout, no shell-outs. Development happens on Windows; public users
will not be on it.

### Commands

| Command | Effect |
|---|---|
| `armoire serve .` | Serve the folder at `127.0.0.1:8420`, `--port` to override. Read-only. |
| `armoire init <template> <path>` | Scaffold a new structured folder. |
| `armoire check .` | Conformance report to stdout, no server. |
| `armoire templates` | List available templates. |

## Templates

A template is a TOML file. It is the single source of structure, consumed by three
different subsystems — scaffolding, validation, and presentation. Each entry
carries the fields all three need, so structure is declared exactly once.

```toml
name = "research-project"
description = "Self-paced quantitative research project"

[present]
home  = "README.md"
order = ["docs", "src", "data", "notebooks"]

[[dir]]
path = "data"
label = "Data"
required = true

[[dir]]
path = "notebooks"
required = false

[[file]]
path = "README.md"
required = true
content = "# {{name}}\n\n{{description}}\n"
```

| Field | Consumed by |
|---|---|
| `path`, `required` | validation |
| `content`, `{{vars}}` | scaffolding |
| `label`, `[present]` | presentation |

Three rules resolve the overlaps between those consumers:

- **Scaffolding creates every declared entry**, whether or not it is `required`.
  `required` affects validation alone — it decides whether a *missing* entry is
  reported as a deviation.
- **`{{vars}}` are supplied on the command line.** `armoire init research-project
  ./0dte --name "0DTE" --description "Term structure study"` substitutes into
  `content`. An unsupplied variable is an error, not an empty string.
- **`[present] order` is a prefix, not a whitelist.** Listed entries appear first in
  the given order; everything else follows alphabetically.

### Nesting

Sibling directories that share a shape reference another template by glob. The
originating folder needs this: `research/` holds three projects of identical shape.

```toml
[[dir]]
path = "research/*"
template = "research-project"
```

One level of reference. Cycles are rejected at load time, not at use time.

### Resolution order

1. `./armoire.toml` — may inline structure or name a template
2. `~/.armoire/templates/`
3. Bundled with the package

Bundled starters: `research-project`, `course`, `notes`, `blank`.

A folder with no `armoire.toml` and no matching template is fully browsable.
Templates are opt-in: without one, the conformance badge and panel are absent and
presentation falls back to alphabetical ordering with `README.md` as the home page
if present. `armoire check` on such a folder reports that no template applies and
exits 0.

## Read-only boundary

`serve` and `check` never write: no editing, renaming, deletion, or git operations.
`init` writes, because creating the folder is its entire purpose. Nothing else
touches disk. This boundary is a test, not a convention.

## Visual design

Light theme only, following GitHub's visual grammar.

| Token | Value |
|---|---|
| Background | `#ffffff` |
| Text | `#1f2328` |
| Link | `#0969da` |
| Border | `#d1d9e0` |
| Subtle fill | `#f6f8fa` |
| Radius | 6px |
| Font | system stack; `ui-monospace, SFMono-Regular, Consolas` for code |

Layout is two-pane: collapsible tree on the left, preview filling the rest, with a
fuzzy filter in the header and a status strip showing size, mtime, and type. A
directory renders as a bordered listing table under a breadcrumb; when it contains
a `README.md`, that file renders in a card below the listing — the behavior GitHub
already trained everyone to expect.

Conformance appears as a quiet badge in the header that opens a panel. It never
blocks or nags.

## Backend — `src/armoire/`

| Module | Single responsibility |
|---|---|
| `paths.py` | Resolve a request path against root; reject escapes. All file access routes through it. |
| `template.py` | Parse and resolve templates; reject cycles. |
| `scaffold.py` | Template + variables → files on disk. |
| `validate.py` | Folder + template → list of deviations. |
| `scanner.py` | One directory → listing. Never recurses. |
| `index.py` | Flat path list for the filter. Background build at startup, disk cache, invalidated by root mtime. |
| `previews/notebook.py` | `.ipynb` → HTML via nbconvert. |
| `previews/table.py` | `.parquet` / `.csv` → schema, row count, one page of rows via lazy polars. |
| `previews/text.py` | md/tex/py/json/txt → text plus detected language. |
| `app.py` | FastAPI routes. Dispatch only. |
| `cli.py` | `serve`, `init`, `check`, `templates`. |

PDFs and images bypass the preview layer entirely — streamed raw with the correct
content-type, rendered natively by the browser.

## Frontend — `static/`

Plain ES modules, no build step.

- `tree.js` — lazy tree; fetches one level per expand
- `filter.js` — fuzzy match over the flat index
- `preview.js` — dispatch on extension
- `renderers/{markdown,notebook,table,pdf,code}.js`

Libraries are vendored locally rather than loaded from a CDN — marked, KaTeX,
mermaid, highlight.js — fetched once by `scripts/vendor.py`. The app works offline
and makes no network request per page load.

The markdown renderer rewrites relative links into in-app navigation, so a
cross-reference like `[data/](data/)` becomes a working link instead of a 404.

## API

```
GET /api/tree?path=…       → {dirs, files: [{name, size, mtime, ext}]}
GET /api/index             → flat path list
GET /api/preview?path=…    → {kind: "markdown"|"notebook"|"table"|"code", …}
GET /api/raw?path=…        → bytes + content-type
GET /api/conformance       → deviations from template
```

The client URL is `/#/research/0dte/README.md`: every file is bookmarkable and the
back button works.

## Safety and performance

The server binds `127.0.0.1` only. It serves arbitrary file bytes from the root, so
it must not be reachable off-machine.

`paths.py` resolves every incoming path and verifies `is_relative_to(root)`.
Symlinks pointing outside root are refused.

No request ever walks the full tree. Ignores — `.git`, `.venv`, `node_modules`,
`__pycache__`, `site-packages`, `.ruff_cache`, `.pytest_cache` — prune the four
nested virtualenvs before they are visited, so the 189k-file figure is never
touched. Parquet is read through `scan_parquet().head()`, so a 2 GB file previews
as fast as a 2 KB one.

## Error handling

| Condition | Response |
|---|---|
| Missing file | 404 card |
| Path outside root | 403 |
| Binary or unsupported type | "No preview" card with size and download link |
| Corrupt parquet or notebook | Error card showing the exception |

A bad file never produces a 500.

## Testing

pytest covers:

- Path jail: `../` traversal, absolute paths, symlink escape
- Ignore-list correctness
- Template resolution, including cycle rejection
- Scaffold output matches the template
- Validation catches missing required entries
- Table pagination boundaries
- One smoke test per renderer endpoint
- The read-only boundary: `serve` and `check` leave the filesystem unmodified

## Decisions and their reasons

**Python backend rather than a Node build step.** Parquet reading and notebook
conversion both require Python server-side. Adding Vite and React would introduce a
second toolchain to support five renderers. No build step means `uvx armoire serve .`
works immediately.

**Standalone tool rather than something living inside `summer-26`.** The requirement
is any folder, and there are roughly forty sibling repos it applies to.

**Nested templates.** They add real complexity to `template.py`, but the originating
folder needs them — `research/` holds three projects of one shape.

**Light theme only.** Reduces surface area; a dark theme can be added later without
disturbing the token structure.
