import polars as pl
import pytest
from fastapi.testclient import TestClient

from armoire.app import create_app


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    # newline="" avoids Windows' universal-newline translation on write, so the
    # byte-exact assertion in test_preview_markdown holds on every platform.
    (tmp_path / "docs" / "readme.md").write_text("# Hi\n", encoding="utf-8", newline="")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "blob.dat").write_bytes(b"\x00\x01\x02")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    pl.DataFrame({"i": [1, 2, 3]}).write_parquet(tmp_path / "d.parquet")
    (tmp_path / ".venv").mkdir()
    (tmp_path / "bad.ipynb").write_text("{not json", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(root):
    app = create_app(root)
    # The index builds on a background thread; without this the index test races.
    app.state.index.wait(timeout=10)
    return TestClient(app)


def test_tree_lists_the_root(client):
    body = client.get("/api/tree", params={"path": ""}).json()
    assert [d["name"] for d in body["dirs"]] == ["docs"]
    assert "code.py" in [f["name"] for f in body["files"]]


def test_tree_omits_ignored_dirs(client):
    body = client.get("/api/tree", params={"path": ""}).json()
    assert ".venv" not in [d["name"] for d in body["dirs"]]


def test_tree_outside_root_is_403(client):
    assert client.get("/api/tree", params={"path": "../.."}).status_code == 403


def test_tree_missing_is_404(client):
    assert client.get("/api/tree", params={"path": "nope"}).status_code == 404


def test_index_reports_paths(client):
    body = client.get("/api/index").json()
    assert "docs/readme.md" in body["paths"]


def test_preview_markdown(client):
    body = client.get("/api/preview", params={"path": "docs/readme.md"}).json()
    assert body["kind"] == "markdown"
    assert body["text"] == "# Hi\n"


def test_preview_code(client):
    body = client.get("/api/preview", params={"path": "code.py"}).json()
    assert body["kind"] == "code"
    assert body["language"] == "python"


def test_preview_table_paginates(client):
    body = client.get("/api/preview", params={"path": "d.parquet", "page": 0}).json()
    assert body["kind"] == "table"
    assert body["total_rows"] == 3


def test_preview_pdf_announces_kind_without_bytes(client):
    body = client.get("/api/preview", params={"path": "doc.pdf"}).json()
    assert body["kind"] == "pdf"
    assert "text" not in body


def test_preview_binary_reports_size(client):
    body = client.get("/api/preview", params={"path": "blob.dat"}).json()
    assert body["kind"] == "binary"
    assert body["size"] == 3


def test_corrupt_notebook_returns_error_card_not_500(client):
    response = client.get("/api/preview", params={"path": "bad.ipynb"})
    assert response.status_code == 200
    assert response.json()["kind"] == "error"


def test_preview_outside_root_is_403(client):
    assert client.get("/api/preview", params={"path": "../secret"}).status_code == 403


def test_raw_streams_pdf_with_content_type(client):
    response = client.get("/api/raw", params={"path": "doc.pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_raw_outside_root_is_403(client):
    assert client.get("/api/raw", params={"path": "../secret"}).status_code == 403


def test_index_html_is_served_at_root(client):
    assert client.get("/").status_code == 200


def test_serving_never_writes_to_disk(root, client):
    def snapshot():
        return {
            p.relative_to(root).as_posix(): p.stat().st_mtime_ns
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    client.get("/api/tree", params={"path": ""})
    client.get("/api/index")
    for name in ["docs/readme.md", "code.py", "d.parquet", "doc.pdf", "blob.dat"]:
        client.get("/api/preview", params={"path": name})
        client.get("/api/raw", params={"path": name})
    assert snapshot() == before
