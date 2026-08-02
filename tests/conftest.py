"""A small sample folder, and a live server in front of it."""

import json
import os
import socket
import subprocess
import threading
import time

import polars as pl
import pytest
import uvicorn

from armoire import store
from armoire.app import create_app


def _redirect_config_root(setenv, setattr_, base) -> None:
    """Point config_root() at `base`, on every platform, without replacing
    config_root() itself.

    tests/test_store.py exercises config_root()'s own platform-dispatch logic
    directly -- each of its platform tests sets sys.platform plus whichever of
    APPDATA / XDG_CONFIG_HOME / store._home that platform's branch reads, and
    asserts the *real* function computes the right path. Replacing
    config_root() wholesale (`monkeypatch.setattr(store, "config_root", ...)`)
    would make every one of those tests observe a stub instead of the function
    they mean to test. Patching what the real implementation reads instead
    keeps that logic intact: a test that overrides one of these three itself
    simply layers its own patch on top of this one, for the one platform
    branch it cares about, exactly as if this fixture were not here.

    All three are set regardless of the platform actually running these
    tests, so the suite stays isolated on whichever of the six CI platform
    combinations runs it.
    """
    setenv("APPDATA", str(base))
    setenv("XDG_CONFIG_HOME", str(base))
    setattr_(store, "_home", lambda: base)


@pytest.fixture(scope="session")
def _isolated_store_session(tmp_path_factory):
    """One store base for the whole test session -- shared by every test,
    function-scoped or session-scoped alike, via `_isolated_store` below.

    This used to be a *separate* store from `_isolated_store`'s own
    per-test directory, which review caught as a real bug in the making:
    task-4-brief.md already has dashboard.project_rows call
    store.read_state(root) per request, and app.py calls that per request
    too. Once that lands, a Playwright test against a session-scoped server
    (whose app was created once, against this session store) would read its
    registry from here but its state.json from wherever *that test's own*
    `_isolated_store` pointed -- silently returning {} instead of erroring,
    in a way that would look like a dashboard.py bug rather than a fixture
    one. `folder_dir` already keys by `sha256(realpath(folder))`, and every
    test's served folder is its own distinct tmp_path/mktemp directory, so
    there is no collision between tests to isolate against by giving each
    one a separate base -- sharing this one removes the disagreement
    entirely, for free.

    The session-scoped fixtures below build their registry file, and their
    server's app (which bakes in that registry's path at creation time), once,
    long before any single test's function-scoped `monkeypatch` exists -- and
    that server keeps running for the rest of the session. A function-scoped
    monkeypatch cannot reach back far enough to cover that: it does not exist
    yet when this setup runs, and it is torn down at the end of whichever
    test happens to trigger this fixture's first use, long before the session
    ends.

    pytest.MonkeyPatch.context() is used directly, as its own context manager,
    rather than the `monkeypatch` fixture (which is function-scoped and cannot
    be requested here). Held open for the whole session by yielding from
    inside the `with` block, so config_root() keeps returning this directory
    for as long as any session-scoped root or server fixture is alive --
    which, once a request registers a background thread serving one of them,
    is the rest of the test run.

    Uses the same environment-redirection as `_redirect_config_root` rather
    than replacing config_root() itself, for the same reason `_isolated_store`
    does: a wholesale replacement held open for the rest of the session would
    just as surely break tests/test_store.py's platform tests whenever they
    happen to run after this fixture's first use.
    """
    base = tmp_path_factory.mktemp("armoire-store-session")
    with pytest.MonkeyPatch.context() as mp:
        _redirect_config_root(mp.setenv, mp.setattr, base)
        yield base


@pytest.fixture(autouse=True)
def _isolated_store(_isolated_store_session):
    """No test may read or write the developer's real armoire store.

    Depends on -- and simply reuses -- _isolated_store_session's one shared
    base rather than pointing at a fresh directory of its own each time (see
    that fixture's docstring for why a separate base was itself a bug).
    Autouse, function-scoped, so it forces the session fixture to be set up
    before the very first test in the run, regardless of whether that test
    is one of the session-scoped Playwright fixtures below.
    """
    return _isolated_store_session


MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""

ROOT_README = """# Sample Folder

Inline math $E = mc^2$ and a display equation:

$$\\int_0^1 x^2 dx = \\frac{1}{3}$$

```mermaid
flowchart LR
  A[Start] --> B[End]
```

See [notes/](notes/) for the nested folder.
"""

# Every cell carries an "id": nbformat_minor 5 requires it, and a fixture
# without one is not shaped like anything Jupyter would actually write.
NOTEBOOK = {
    "cells": [
        {
            "cell_type": "markdown",
            "id": "intro",
            "metadata": {},
            "source": ["# Notebook Heading\n"],
        },
        {
            "cell_type": "code",
            "id": "emit",
            "execution_count": 1,
            "metadata": {},
            "source": ["print('notebook output')\n"],
            "outputs": [{"output_type": "stream", "name": "stdout", "text": ["notebook output\n"]}],
        },
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}


@pytest.fixture(scope="session")
def sample_root(tmp_path_factory, _isolated_store_session):
    root = tmp_path_factory.mktemp("sample")
    # newline="" avoids Windows' universal-newline translation on write, so
    # the markdown renderer's exact `\n`-anchored mermaid-fence regex sees
    # the same bytes on every platform.
    (root / "README.md").write_text(ROOT_README, encoding="utf-8", newline="")
    # The same document with CRLF endings. Windows editors and git's autocrlf
    # produce these routinely -- 8 of the 11 mermaid documents in the folder
    # armoire was built for are CRLF -- so the renderer must handle both.
    (root / "crlf.md").write_bytes(ROOT_README.replace("\n", "\r\n").encode("utf-8"))
    (root / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="")
    (root / "doc.pdf").write_bytes(MINIMAL_PDF)
    (root / "blob.dat").write_bytes(b"\x00\x01\x02\x03")
    (root / "nb.ipynb").write_text(json.dumps(NOTEBOOK), encoding="utf-8", newline="")
    (root / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n"
        "Some text.\n\\end{document}\n",
        encoding="utf-8",
        newline="",
    )
    (root / "config.toml").write_text('[section]\nkey = "value"\n', encoding="utf-8", newline="")
    (root / "hostile.md").write_text(
        "# Hostile\n\n"
        '<img src=x onerror="window.__pwned = true">\n\n'
        # No spaces in the destination: marked's CommonMark-compliant link
        # parser rejects an unenclosed space in a link destination and never
        # emits an <a> tag at all for one, which would make this vector
        # untestable for reasons that have nothing to do with the sanitizer.
        "[click me](javascript:window.__pwned=true)\n",
        encoding="utf-8",
        newline="",
    )
    pl.DataFrame({"i": range(250), "label": [f"r{n}" for n in range(250)]}).write_parquet(
        root / "data.parquet"
    )
    # "%" is not a valid percent-escape by itself; decodeURIComponent throws
    # on it unless every write to location.hash first encodes the segment.
    (root / "50% off.md").write_text(
        "# Percent\n\nA name with a literal percent sign.\n", encoding="utf-8", newline=""
    )
    # rewriteLinks (renderers/markdown.js) is a third hash-write site, distinct
    # from navigate() and the breadcrumb: a relative link to a percent-named
    # file must round-trip through the same encoding as the other two. Named
    # "100%.md" rather than reusing "50% off.md" -- marked itself partially
    # encodes a raw space in a link destination (leaves "%" untouched but
    # turns " " into "%20"), which would confound this test with marked's own
    # quirk rather than isolating rewriteLinks's. A bare "%" with no adjacent
    # space passes through marked unmodified, verified empirically.
    (root / "100%.md").write_text(
        "# Percent Only\n\nA name with a literal percent sign and no space.\n",
        encoding="utf-8",
        newline="",
    )
    (root / "links.md").write_text("# Links\n\n[percent](100%.md)\n", encoding="utf-8", newline="")

    notes = root / "notes"
    notes.mkdir()
    (notes / "README.md").write_text(
        "# Notes\n\nNested folder readme.\n", encoding="utf-8", newline=""
    )
    (notes / "deep").mkdir()
    (notes / "deep" / "buried.md").write_text("# Buried\n", encoding="utf-8", newline="")

    ignored = root / ".venv"
    ignored.mkdir()
    (ignored / "junk.py").write_text("noise\n", encoding="utf-8", newline="")

    # A folder literally named "browse". The prefix scheme exists so this
    # cannot collide with the route; without a fixture, nothing proves it.
    collide = root / "browse"
    collide.mkdir()
    (collide / "inside.md").write_bytes(b"# Inside a folder named browse\n")

    # A registry makes the roadmap appear. Two nodes and one edge is the
    # smallest graph that exercises layout, an edge, and a blocked node.
    # Written into the store, not the served folder: describing a folder must
    # not modify it.
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        "[[project]]\n"
        'name = "Downstream"\n'
        'paths = ["notes"]\n'
        'blocked_by = ["Upstream"]\n'
        'category = "research"\n'
        "due = 2026-08-17\n"
        "\n"
        "[[project]]\n"
        'name = "Upstream"\n'
        'paths = ["notes/deep"]\n'
        'category = "learning"\n',
        encoding="utf-8",
        newline="",
    )
    return root


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(sample_root):
    app = create_app(sample_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start within 10s")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def bare_root(tmp_path_factory, _isolated_store_session):
    """A folder with no registry -- the state every folder starts in.

    Depends on _isolated_store_session even though it writes nothing there:
    bare_server's create_app() call still resolves store.registry_path(root)
    at creation time, and that must resolve under the session's isolated
    store rather than the developer's real one.
    """
    root = tmp_path_factory.mktemp("bare")
    (root / "README.md").write_bytes(b"# Bare\n\nNo registry here.\n")
    return root


@pytest.fixture(scope="session")
def bare_server(bare_root):
    app = create_app(bare_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("bare server did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def empty_registry_root(tmp_path_factory, _isolated_store_session):
    """Zero [[project]] entries -- valid TOML, no RegistryError, but nothing
    for renderRoadmap to lay out. app.js never calls renderRoadmap with this:
    it falls back to the file browser, the same exit a missing registry
    file takes."""
    root = tmp_path_factory.mktemp("empty-registry")
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        "# No [[project]] entries -- still a valid registry.\n",
        encoding="utf-8",
        newline="",
    )
    return root


@pytest.fixture(scope="session")
def empty_registry_server(empty_registry_root):
    app = create_app(empty_registry_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("empty-registry server did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def colon_name_root(tmp_path_factory, _isolated_store_session):
    """A project whose name contains a colon, with a genuine issue against it
    (a missing path) -- the fixture Finding 2's flagged-set fix needs to
    prove itself against."""
    root = tmp_path_factory.mktemp("colon-name")
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        '[[project]]\nname = "Foo: Bar"\npaths = ["missing"]\n',
        encoding="utf-8",
        newline="",
    )
    return root


@pytest.fixture(scope="session")
def colon_name_server(colon_name_root):
    app = create_app(colon_name_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("colon-name server did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _git(cwd, *args):
    """Run git under a fixed identity. The one copy; test_activity and
    test_dashboard import it rather than keeping their own.

    The identity is merged *over* os.environ, not substituted for it. A
    replacement environment carrying only PATH drops HOME, SYSTEMROOT and
    everything else git may need, and the platform that first minds is not the
    one you develop on -- CI runs six platform/version combinations. The
    failure also lands badly: this runs inside session-scoped fixtures, so one
    CalledProcessError whose captured output nobody prints takes out every
    Playwright test depending on committed_server at once.

    The four identity variables stay explicit so the isolation intent survives:
    commits must not be attributed to whoever is running the suite.

    Inheriting the environment inherits the runner's git configuration too,
    which is the same blast radius from the other side: `commit.gpgsign = true`
    in someone's ~/.gitconfig would fail every commit here, and a
    `core.hooksPath` or `commit.template` would be just as fatal. CI images
    carry no global config, so this bites a developer rather than the matrix.
    Pointing both config scopes at os.devnull keeps the real environment
    without the ambient settings -- git reads the file, finds nothing, and
    falls back to the identity above.
    """
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=os.environ
        | {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )


@pytest.fixture(scope="session")
def committed_root(tmp_path_factory, _isolated_store_session):
    """A registry with one project whose folder has real git history.

    sample_root has none at all -- confirmed by reading its own fixture code,
    which never calls `git init` -- so neither of its two projects can
    exercise the commit-row markup project.js renders from `/api/project`'s
    `commits` list. This fixture exists so that markup has something real to
    render against.
    """
    root = tmp_path_factory.mktemp("committed")
    project = root / "worked"
    project.mkdir()
    (project / "a.txt").write_text("1", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first worked commit")
    (project / "a.txt").write_text("2", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "second worked commit")
    registry_file = store.registry_path(root)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        '[[project]]\nname = "Worked"\npaths = ["worked"]\n',
        encoding="utf-8",
        newline="",
    )
    return root


@pytest.fixture(scope="session")
def committed_server(committed_root):
    app = create_app(committed_root)
    app.state.index.wait(timeout=10)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("committed server did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
