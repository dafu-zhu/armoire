# armoire

Serve any folder as a local, read-only website.

A folder that accumulates hundreds of documents becomes unbrowsable. File managers
show names and nothing else; opening a notebook or a parquet file means launching a
separate tool; relative links between READMEs are dead. armoire renders the folder
in a browser — markdown with math and diagrams, PDFs, notebooks with their outputs,
and parquet/CSV as paginated tables — and can check the folder against a structure
you declare.

```console
$ uvx armoire serve .                          # browse at 127.0.0.1:8420
$ uvx armoire init research-project ./0dte     # scaffold a structured folder
$ uvx armoire check .                          # report drift from the template
```

`serve` and `check` never write. `init` is the only command that touches disk.

## Status

The viewer works: browse any folder and read markdown (with math and diagrams),
PDFs, notebooks, code, and parquet/CSV tables. Templates, scaffolding, and
conformance checking are next.

Install from source until the first release:

    git clone https://github.com/dafu-zhu/armoire
    cd armoire
    uv sync
    uv run armoire serve /path/to/folder

## License

MIT
