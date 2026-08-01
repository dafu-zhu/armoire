import datetime as dt
import json
from decimal import Decimal

import polars as pl
import pytest

from armoire.previews.table import MAX_PAGE_SIZE, preview_table


@pytest.fixture
def parquet(tmp_path):
    path = tmp_path / "d.parquet"
    pl.DataFrame({"i": range(250), "label": [f"r{n}" for n in range(250)]}).write_parquet(path)
    return path


@pytest.fixture
def csv(tmp_path):
    path = tmp_path / "d.csv"
    pl.DataFrame({"i": [1, 2, 3]}).write_csv(path)
    return path


@pytest.fixture
def rich_types(tmp_path):
    path = tmp_path / "rich.parquet"
    pl.DataFrame(
        {
            "when": [dt.datetime(2026, 8, 1, 12, 30)],
            "amount": [Decimal("1.25")],
            "nothing": [None],
        }
    ).write_parquet(path)
    return path


def test_reports_schema(parquet):
    result = preview_table(parquet)
    assert result["kind"] == "table"
    assert [c["name"] for c in result["columns"]] == ["i", "label"]
    assert result["columns"][0]["dtype"] == "Int64"


def test_reports_total_rows_not_page_length(parquet):
    result = preview_table(parquet, page=0, page_size=100)
    assert result["total_rows"] == 250
    assert len(result["rows"]) == 100


def test_second_page_starts_where_first_ended(parquet):
    assert preview_table(parquet, page=1, page_size=100)["rows"][0][0] == "100"


def test_final_partial_page(parquet):
    assert len(preview_table(parquet, page=2, page_size=100)["rows"]) == 50


def test_page_past_the_end_is_empty_not_an_error(parquet):
    assert preview_table(parquet, page=99, page_size=100)["rows"] == []


def test_negative_page_is_clamped_to_zero(parquet):
    assert preview_table(parquet, page=-1)["page"] == 0


def test_reads_csv_too(csv):
    assert preview_table(csv)["total_rows"] == 3


def test_oversized_page_size_is_clamped_and_reported(parquet):
    result = preview_table(parquet, page_size=10_000)
    assert result["page_size"] == MAX_PAGE_SIZE
    assert len(result["rows"]) == MAX_PAGE_SIZE or len(result["rows"]) == result["total_rows"]


def test_zero_page_size_is_clamped_to_one(parquet):
    result = preview_table(parquet, page_size=0)
    assert result["page_size"] == 1
    assert len(result["rows"]) == 1


def test_non_primitive_types_survive_json_serialisation(rich_types):
    result = preview_table(rich_types)
    json.dumps(result["rows"])  # would raise on a raw datetime or Decimal
    when, amount, nothing = result["rows"][0]
    assert isinstance(when, str) and "2026-08-01" in when
    assert isinstance(amount, str) and "1.25" in amount
    assert nothing is None


def test_unsupported_file_format_raises(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("a\tb\n1\t2\n")
    with pytest.raises(ValueError, match="unsupported table format"):
        preview_table(path)
