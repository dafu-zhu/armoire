import polars as pl
import pytest

from armoire.previews.table import preview_table


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


def test_rows_are_json_serialisable(parquet):
    import json

    json.dumps(preview_table(parquet)["rows"])
