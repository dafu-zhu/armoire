"""HTTP surface. Routing and error translation only — no logic lives here."""

import logging
import mimetypes
import threading
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from armoire import dashboard, store
from armoire.index import PathIndex
from armoire.paths import PathOutsideRoot, resolve_in_root
from armoire.previews import extension_of, kind_for
from armoire.previews.notebook import preview_notebook
from armoire.previews.table import preview_table
from armoire.previews.text import preview_text
from armoire.projects import STATUSES, RegistryError, load_registry
from armoire.scanner import list_dir

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Serialises the read-merge-write in set_status. Module level, not per app:
# the state file is keyed by the served folder, and two apps created for the
# same folder in one process (the test suite does exactly this) write the same
# file. FastAPI runs `def` handlers in a threadpool, so two PUTs arriving
# together really do run in parallel threads -- without this they both read
# the same state, each merges only its own project into it, and whichever
# writes last silently drops the other's edit. Held across the read and the
# write, since that whole span is the critical section; a lock around the
# write alone would still lose the update.
#
# "Writes are last-write-wins" (the spec) is a statement about two edits to
# the *same* project, not permission to lose an edit to a different one.
_state_lock = threading.Lock()


def _resolve(root: Path, path: str) -> Path:
    try:
        return resolve_in_root(root, path)
    except PathOutsideRoot:
        raise HTTPException(status_code=403, detail="path is outside the served root") from None


def create_app(root: Path) -> FastAPI:
    root = root.resolve()
    # The store's location is a creation-time concern, and this is the one
    # place it is decided. store.folder_dir() calls store.config_root(),
    # which reads an environment variable; a long-lived server must not have
    # to keep re-reading it correctly for the rest of the process's life.
    #
    # Everything downstream is derived from this one resolved directory --
    # the registry read, the state read, the state write, and the refusal
    # that guards the write (store.writes_inside asks its question about
    # exactly this directory). No handler re-enters config_root(). Half of
    # this used to be frozen and half resolved per request, which made
    # test isolation depend on patching config_root() *before* create_app and
    # would have half-applied, silently, if written the other way round.
    store_dir = store.folder_dir(root)
    registry_file = store_dir / store.REGISTRY_FILE
    state_file = store_dir / store.STATE_FILE
    writes_into_root = store.writes_inside(root)
    app = FastAPI(title="armoire", docs_url=None, redoc_url=None)

    index = PathIndex(root)
    index.start()
    # Exposed so tests and later commands can await the background walk.
    app.state.index = index

    @app.get("/api/tree")
    def tree(path: str = Query("")) -> dict:
        try:
            dirs, files = list_dir(root, path)
        except PathOutsideRoot:
            raise HTTPException(status_code=403, detail="path is outside the served root") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="no such directory") from None
        payload = {
            "path": path,
            "dirs": [asdict(d) for d in dirs],
            "files": [asdict(f) for f in files],
        }
        if path == "":
            # Root metadata: identical on every response, and only tree.js's
            # initial, root-level fetch ever reads it (see app.js's
            # tree.ready handling) -- nothing downstream refetches it per
            # navigation. dashboard.has_roadmap parses the registry, so
            # computing it on every subdirectory expansion too would be pure
            # waste for a value nothing there consults.
            payload["root"] = str(root)
            payload["has_registry"] = dashboard.has_roadmap(root, registry_file)
        return payload

    @app.get("/api/index")
    def flat_index() -> dict:
        return {"ready": index.ready, "paths": index.paths}

    @app.get("/api/preview")
    def preview(path: str = Query(...), page: int = Query(0)) -> dict:
        target = _resolve(root, path)
        if target.is_dir():
            raise HTTPException(status_code=404, detail="no such file: is a directory")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no such file")

        stat = target.stat()
        # Every payload carries size and mtime so the status bar can show them
        # without a second request, whatever the kind turns out to be.
        envelope = {"size": stat.st_size, "mtime": stat.st_mtime}

        kind = kind_for(extension_of(target))
        try:
            if kind in ("markdown", "code"):
                return envelope | preview_text(target, kind)
            if kind == "table":
                return envelope | preview_table(target, page=page)
            if kind == "notebook":
                return envelope | preview_notebook(target)
        except Exception as exc:
            # A corrupt file is a rendering problem, not a server fault. The
            # client shows an error card; the server stays up.
            logger.exception("preview failed for %s", path)
            return envelope | {"kind": "error", "message": str(exc)}

        # pdf, image and binary are fetched from /api/raw by the client.
        return envelope | {"kind": kind}

    @app.get("/api/raw")
    def raw(path: str = Query(...)) -> FileResponse:
        target = _resolve(root, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        media_type, _ = mimetypes.guess_type(target.name)
        kind = kind_for(extension_of(target))
        # Only the kinds the client embeds are served inline, and SVG is
        # excluded even though its kind is "image": browsers execute scripts in
        # an SVG opened as a top-level document, which would run in armoire's
        # own origin. Content-Disposition is ignored for <img> subresource
        # loads, so the image renderer is unaffected.
        inline = kind == "pdf" or (kind == "image" and extension_of(target) != "svg")
        disposition = "inline" if inline else "attachment"
        # RFC 6266. Starlette latin-1 encodes header values, so the bare
        # filename= must be ASCII; filename*= carries the real name. Without
        # this, any non-Latin-1 filename raises inside the handler and 500s.
        # encode("ascii", "replace") only maps non-ASCII code points to "?";
        # it leaves ASCII control bytes (e.g. CR/LF, illegal on Windows but
        # legal on Linux ext4) intact, so isprintable() also filters those.
        ascii_name = "".join(
            c
            for c in target.name.encode("ascii", "replace").decode("ascii")
            if c.isprintable() and c != '"'
        )
        content_disposition = (
            f'{disposition}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(target.name, safe='')}"
        )
        return FileResponse(
            target,
            media_type=media_type or "application/octet-stream",
            headers={
                "Content-Disposition": content_disposition,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/projects")
    def projects() -> dict:
        envelope = {"root": str(root), "projects": [], "issues": []}
        try:
            registry = load_registry(root, registry_file)
        except RegistryError as exc:
            # 200, not 4xx: the client must still render the page and show
            # which line was wrong. A status code hides that behind the
            # generic error path.
            logger.warning("registry failed to load: %s", exc)
            return envelope | {"error": str(exc)}
        if registry is None:
            return envelope | {"registry": False}

        return envelope | {
            "projects": dashboard.project_rows(registry, state_file),
            "issues": registry.issues,
        }

    @app.get("/api/project/{name}")
    def project_detail(name: str) -> dict:
        try:
            registry = load_registry(root, registry_file)
        except RegistryError as exc:
            # 404 rather than the 200+error shape /api/projects uses: that endpoint
            # must render a page and show the parse message, this one is only
            # reachable from a roadmap that already loaded. The message still
            # travels in `detail`.
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if registry is None:
            raise HTTPException(status_code=404, detail="no registry")

        detail = dashboard.project_detail(root, registry, name, state_file)
        if detail is None:
            raise HTTPException(status_code=404, detail="no such project")
        return detail

    @app.put("/api/status")
    def set_status(payload: dict, request: Request) -> dict:
        # The bind address stops other machines, not other tabs: any page in
        # any browser on this machine can reach 127.0.0.1. What actually keeps
        # a script on a foreign origin from reaching this handler through the
        # browser is that PUT is not a CORS "simple method": the browser
        # refuses to send it cross-origin without first sending an OPTIONS
        # preflight, armoire answers no CORS headers and installs no CORS
        # middleware, so the preflight fails closed and the real PUT is never
        # sent. X-Armoire is belt-and-braces on top of that, not the sole
        # barrier -- it also closes the HTML-form-post route in, since a form
        # cannot set a custom header at all.
        #
        # The Origin check below is a same-origin *self-consistency* check,
        # not an allowlist: request.base_url is derived from this same
        # request's own Host header, so "Origin equals base_url" holds
        # tautologically for a request whose Host has been DNS-rebound to
        # 127.0.0.1 -- the browser considers that request same-origin, sends
        # no preflight, and lets script set X-Armoire freely. That is a real
        # bypass of both checks above at once, so the Host header itself is
        # pinned to a fixed loopback allowlist here, independent of anything
        # the request claims about its own Origin or Host.
        if request.headers.get("X-Armoire") != "1":
            raise HTTPException(status_code=403, detail="missing X-Armoire header")
        # request.url.hostname, not a hand-split Host header: a bracketed
        # IPv6 literal ("[::1]:8420") contains colons of its own, so
        # splitting on ":" takes the wrong piece and a genuine IPv6-loopback
        # request would be refused. The URL parser already strips the
        # brackets, so the bracketed spelling never appears in the allowlist
        # itself -- only the unwrapped "::1" does.
        host = request.url.hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise HTTPException(status_code=403, detail="foreign host")
        origin = request.headers.get("Origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="foreign origin")
        # Decided at creation time, with the paths it protects, rather than
        # re-asked here: state_file is fixed for this app's lifetime, so
        # whether writing it lands inside the served folder is fixed too.
        # The question is about that write target and not about config_root()
        # as a whole -- serving a descendant of config_root() (config_root()
        # itself, or its own "folders" tree) puts the store directory inside
        # root even though config_root() is not inside root, the other way
        # around, and this handler would write into the tree it is serving.
        if writes_into_root:
            raise HTTPException(
                status_code=403, detail="the armoire store is inside the served folder"
            )

        status = payload.get("status")
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"unknown status {status!r}")
        name = payload.get("name")

        try:
            registry = load_registry(root, registry_file)
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if registry is None or not any(p.name == name for p in registry.projects):
            raise HTTPException(status_code=404, detail="no such project")

        # Read, merge and write under one lock: state.json is rewritten
        # whole, so two threads that read it before either writes each
        # produce a document missing the other's edit. See _state_lock.
        with _state_lock:
            state = store.read_state(state_file)
            # An entry naming a project the registry no longer has is kept, not
            # pruned: renaming a project and renaming it back should not lose its
            # status.
            statuses = state.get("status")
            state["status"] = (statuses if isinstance(statuses, dict) else {}) | {name: status}
            store.write_state(state_file, state)
        return {"name": name, "status": status}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
