"""Parquet and CSV, read lazily.

Everything here goes through polars' lazy API. A 2 GB parquet file previews as
fast as a 2 KB one because only the requested slice is ever materialised.
"""

from pathlib import Path

import polars as pl

MAX_PAGE_SIZE = 500


def _scan(path: Path) -> pl.LazyFrame:
    if path.suffix.lower() == ".parquet":
        return pl.scan_parquet(path)
    return pl.scan_csv(path)


def preview_table(path: Path, page: int = 0, page_size: int = 100) -> dict:
    page = max(0, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    frame = _scan(path)
    schema = frame.collect_schema()
    total_rows = frame.select(pl.len()).collect().item()
    window = frame.slice(page * page_size, page_size).collect()

    return {
        "kind": "table",
        "columns": [{"name": name, "dtype": str(dtype)} for name, dtype in schema.items()],
        # str() on every cell keeps datetimes, decimals and nested types
        # JSON-serialisable without a custom encoder.
        "rows": [[None if v is None else str(v) for v in row] for row in window.rows()],
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
    }
