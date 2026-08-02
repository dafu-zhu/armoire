import hashlib
import json
import sys

import polars as pl
import pytest
from fastapi.testclient import TestClient

from armoire import store
from armoire.app import create_app
from armoire.projects import STATUSES

# A minimal but valid notebook: nbformat_minor 5 requires every cell to carry
# an "id". Deliberately distinct from bad.ipynb (which fails at nbformat.read
# and never reaches nbconvert) -- this one reaches HTMLExporter, the one
# dependency in the preview path that plausibly touches a filesystem cache
# such as ~/.jupyter.
GOOD_NOTEBOOK = {
    "cells": [
        {
            "cell_type": "code",
            "id": "only-cell",
            "execution_count": 1,
            "metadata": {},
            "source": ["1 + 1\n"],
            "outputs": [],
        }
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}


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
    (tmp_path / "good.ipynb").write_text(json.dumps(GOOD_NOTEBOOK), encoding="utf-8")
    (tmp_path / "evil.html").write_bytes(b"<script>alert(document.cookie)</script>")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "pic.svg").write_bytes(b'<svg onload="alert(document.cookie)"></svg>')
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


def test_raw_pdf_is_served_inline(client):
    response = client.get("/api/raw", params={"path": "doc.pdf"})
    assert response.headers["content-disposition"].startswith("inline")


def test_raw_html_is_forced_to_download(client):
    response = client.get("/api/raw", params={"path": "evil.html"})
    assert response.headers["content-disposition"].startswith("attachment")


def test_raw_raster_image_is_served_inline(client):
    response = client.get("/api/raw", params={"path": "pic.png"})
    assert response.headers["content-disposition"].startswith("inline")


def test_raw_svg_is_forced_to_download(client):
    """Direct navigation to /api/raw?path=x.svg executes <script> in an SVG as a
    top-level document, in armoire's own origin. <img> subresource loads ignore
    Content-Disposition, so the image preview renderer is unaffected."""
    response = client.get("/api/raw", params={"path": "pic.svg"})
    assert response.headers["content-disposition"].startswith("attachment")


def test_raw_responses_are_nosniff(client):
    response = client.get("/api/raw", params={"path": "doc.pdf"})
    assert response.headers["x-content-type-options"] == "nosniff"


def test_raw_cjk_filename_does_not_500(root):
    """Starlette latin-1 encodes header values; a bare filename= with a CJK
    name used to raise UnicodeEncodeError inside the handler and 500."""
    (root / "报告.pdf").write_bytes(b"%PDF-1.4\n")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/raw", params={"path": "报告.pdf"})
    assert response.status_code == 200
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf" in response.headers["content-disposition"]


def test_raw_accented_latin_filename_does_not_500(root):
    (root / "résumé.pdf").write_bytes(b"%PDF-1.4\n")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/raw", params={"path": "résumé.pdf"})
    assert response.status_code == 200
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in response.headers["content-disposition"]


@pytest.mark.skipif(
    sys.platform == "win32", reason="double quote is not a legal Windows filename character"
)
def test_raw_filename_with_a_quote_produces_a_well_formed_header(root):
    (root / 'a"b.pdf').write_bytes(b"%PDF-1.4\n")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/raw", params={"path": 'a"b.pdf'})
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    # Exactly the two quotes bounding filename="..."; an embedded, unescaped
    # quote in the name would otherwise break out of the quoted-string.
    assert disposition.count('"') == 2


def test_index_html_is_served_at_root(client):
    assert client.get("/").status_code == 200


def test_serving_never_writes_to_disk(root):
    # Written into the store, not the shared `root` fixture: the registry no
    # longer lives inside the served folder at all, and writing it there would
    # also perturb the ~40 tree and index tests that count what is in the
    # folder. But without one, the two Phase 2 calls below get `registry:
    # false` and a 404 -- load_registry never parses, dashboard never
    # composes, activity never invokes git -- so the only write-capable
    # surface Phase 2 added would sit outside the checksum window entirely.
    # "docs" is a real directory in the fixture, so recent_commits and list_dir
    # both do real work against it, via project_detail below.
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        '[[project]]\nname = "Docs"\npaths = ["docs"]\ncategory = "docs"\n', encoding="utf-8"
    )

    def snapshot():
        return {
            p.relative_to(root).as_posix(): (
                p.stat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    # Deliberately does not depend on the `client` fixture: that fixture
    # already calls create_app() and index.wait() before the test body runs,
    # which would put the background index build -- the walk most likely to
    # touch the filesystem -- outside the measured window. Snapshotting
    # first and only then creating the app keeps the whole build inside it.
    before = snapshot()
    app = create_app(root)
    app.state.index.wait(timeout=10)
    client = TestClient(app)

    client.get("/api/tree", params={"path": ""})
    client.get("/api/index")
    for name in [
        "docs/readme.md",
        "code.py",
        "d.parquet",
        "doc.pdf",
        "blob.dat",
        "bad.ipynb",
        "good.ipynb",  # the only fixture file that reaches nbconvert's HTMLExporter
        "evil.html",
        "pic.png",
        "pic.svg",
    ]:
        client.get("/api/preview", params={"path": name})
        client.get("/api/raw", params={"path": name})
    projects = client.get("/api/projects")
    detail = client.get("/api/project/Docs")
    # The snapshot is only as strong as what ran inside it. Assert both calls
    # actually reached their work, so this test cannot quietly go back to
    # checksumming a `registry: false` and a 404 the way it used to.
    assert projects.json()["projects"], projects.json()
    assert detail.status_code == 200, detail.text
    # 200 alone proves the registry parsed and the project resolved; it does
    # not prove list_dir walked anything. The files are what put the scan
    # inside the window.
    assert detail.json()["files"], detail.json()
    assert snapshot() == before


REGISTRY = """
[[project]]
name = "Downstream"
paths = ["docs"]
blocked_by = ["Upstream"]
category = "research"
due = 2026-08-17
note = "a note"

[[project]]
name = "Upstream"
paths = ["docs"]
category = "core"
"""


@pytest.fixture
def registry_root(root):
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(REGISTRY, encoding="utf-8")
    return root


@pytest.fixture
def registry_client(registry_root):
    app = create_app(registry_root)
    app.state.index.wait(timeout=10)
    return TestClient(app)


def test_projects_endpoint_lists_declared_projects(registry_client):
    body = registry_client.get("/api/projects").json()
    assert [p["name"] for p in body["projects"]] == ["Downstream", "Upstream"]
    assert body["issues"] == []


def test_projects_endpoint_carries_optional_fields(registry_client):
    body = registry_client.get("/api/projects").json()
    downstream = body["projects"][0]
    assert downstream["blocked_by"] == ["Upstream"]
    assert downstream["category"] == "research"
    assert downstream["due"] == "2026-08-17"
    assert downstream["note"] == "a note"


def test_projects_endpoint_reports_isolation_and_status_so_the_graph_needs_one_call(
    registry_client,
):
    body = registry_client.get("/api/projects").json()
    assert all(isinstance(p["isolated"], bool) for p in body["projects"])
    assert all(p["status"] in STATUSES for p in body["projects"])
    assert all("commits" not in p and "last" not in p for p in body["projects"])


def test_no_registry_reports_that_rather_than_erroring(client):
    body = client.get("/api/projects").json()
    assert body["registry"] is False
    assert body["projects"] == []


def test_the_stores_registry_wins_over_a_stale_copy_in_the_served_folder(root):
    """prepare_store's migration message claims the folder's own copy is
    ignored once the store already has a registry -- this is what proves it,
    at the layer that actually serves requests: app.py reads exclusively from
    store.registry_path(root) and never looks at the served folder's own
    armoire.toml at all, regardless of what it contains."""
    (root / "armoire.toml").write_text(
        '[[project]]\nname = "Folder"\npaths = ["docs"]\ncategory = "x"\n', encoding="utf-8"
    )
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        '[[project]]\nname = "Store"\npaths = ["docs"]\ncategory = "x"\n', encoding="utf-8"
    )
    app = create_app(root)
    app.state.index.wait(timeout=10)
    body = TestClient(app).get("/api/projects").json()
    assert [p["name"] for p in body["projects"]] == ["Store"]


def test_malformed_registry_is_200_with_an_error_field(root):
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text("[[project]\nname = ", encoding="utf-8")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/projects")
    assert response.status_code == 200
    assert "error" in response.json()


def test_a_structurally_wrong_registry_is_200_with_an_error_field(root):
    """`[project]` with one bracket is valid TOML, so it never reaches the
    TOMLDecodeError arm. It used to escape load_registry as an AttributeError
    and 500 with a text/plain body, which app.js then failed to parse as JSON.
    The documented contract is 200 plus the message."""
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text('[project]\nname = "A"\npaths = ["docs"]\n', encoding="utf-8")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/projects")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "[[project]]" in response.json()["error"]


def test_project_detail_on_a_structurally_wrong_registry_is_404_not_500(root):
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text('[project]\nname = "A"\npaths = ["docs"]\n', encoding="utf-8")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/project/A")
    assert response.status_code == 404
    assert "[[project]]" in response.json()["detail"]


def test_project_detail_on_a_malformed_registry_is_404_carrying_the_parse_error(root):
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text("[[project]\nname = ", encoding="utf-8")
    app = create_app(root)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/project/Anything")
    assert response.status_code == 404
    # The store path, not the literal string "armoire.toml": that constant no
    # longer names the file actually read once the registry lives in the
    # store, and pinning it here would hide a regression back to mislabelling
    # the error with the wrong filename.
    assert str(registry_file) in response.json()["detail"]


def test_project_detail_reports_what_it_blocks(registry_client):
    body = registry_client.get("/api/project/Upstream").json()
    assert body["blocks"] == ["Downstream"]


def test_project_detail_lists_files_under_its_paths(registry_client):
    body = registry_client.get("/api/project/Downstream").json()
    assert any(f["name"] == "readme.md" for f in body["files"])


def test_unknown_project_is_404(registry_client):
    assert registry_client.get("/api/project/Ghost").status_code == 404


def test_a_slashed_project_name_never_reaches_the_handler(registry_client):
    """Starlette's single-segment path converter rejects it before dispatch.

    This is a framework guarantee, not something project_detail implements —
    removing the route's own 404 guard leaves this test green. Named for what
    it proves so nobody mistakes it for a check on the handler.
    """
    assert registry_client.get("/api/project/..%2F..%2Fetc").status_code == 404
    assert registry_client.get("/api/project/A/../..").status_code == 404


def test_a_registry_path_escaping_the_root_yields_no_files(tmp_path):
    """The registry is authored by whoever owns the folder, and armoire gets
    pointed at cloned repositories. An escaping path must return nothing.

    Built like its sibling in test_projects.py rather than around a
    `../../Windows` literal: that literal named a folder that does not exist on
    any of the platforms this suite runs on, so the escape was never tested
    against a target that was actually there. Here the target exists and holds
    a file, which is the case where a missing jail would leak something.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"# Secret\n")
    served = tmp_path / "a" / "b"
    served.mkdir(parents=True)
    registry_file = store.registry_path(served)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        '[[project]]\nname = "Evil"\npaths = ["../../outside"]\n', encoding="utf-8"
    )
    app = create_app(served)
    app.state.index.wait(timeout=10)
    response = TestClient(app).get("/api/project/Evil")
    assert (served / ".." / ".." / "outside" / "secret.md").exists()
    assert response.status_code == 200
    assert response.json()["files"] == []
