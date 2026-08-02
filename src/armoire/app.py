"""HTTP surface. Routing and error translation only — no logic lives here."""

import logging
import mimetypes
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from armoire.activity import activity_for, recent_commits
from armoire.index import PathIndex
from armoire.paths import PathOutsideRoot, resolve_in_root
from armoire.previews import extension_of, kind_for
from armoire.previews.notebook import preview_notebook
from armoire.previews.table import preview_table
from armoire.previews.text import preview_text
from armoire.projects import RegistryError, load_registry
from armoire.scanner import list_dir

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _resolve(root: Path, path: str) -> Path:
    try:
        return resolve_in_root(root, path)
    except PathOutsideRoot:
        raise HTTPException(status_code=403, detail="path is outside the served root") from None


def create_app(root: Path) -> FastAPI:
    root = root.resolve()
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
        return {
            "path": path,
            "dirs": [asdict(d) for d in dirs],
            "files": [asdict(f) for f in files],
        }

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
            registry = load_registry(root)
        except RegistryError as exc:
            # 200, not 4xx: the client must still render the page and show
            # which line was wrong. A status code hides that behind the
            # generic error path.
            logger.warning("registry failed to load: %s", exc)
            return envelope | {"error": str(exc)}
        if registry is None:
            return envelope | {"registry": False}

        listed = []
        for project in registry.projects:
            merged = {"commits": 0, "last": None}
            for relative in project.paths:
                found = activity_for(root, relative)
                merged["commits"] += found.commits
                if found.last is not None:
                    merged["last"] = max(merged["last"] or 0.0, found.last)
            listed.append(
                asdict(project)
                | {"paths": list(project.paths), "blocked_by": list(project.blocked_by)}
                | merged
            )
        return envelope | {"projects": listed, "issues": registry.issues}

    @app.get("/api/project/{name}")
    def project_detail(name: str) -> dict:
        try:
            registry = load_registry(root)
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if registry is None:
            raise HTTPException(status_code=404, detail="no registry")

        match = next((p for p in registry.projects if p.name == name), None)
        if match is None:
            raise HTTPException(status_code=404, detail="no such project")

        files = []
        for relative in match.paths:
            try:
                dirs, entries = list_dir(root, relative)
            except (PathOutsideRoot, FileNotFoundError):
                continue
            for entry in [*dirs, *entries]:
                files.append(
                    {
                        "path": f"{relative}/{entry.name}",
                        "name": entry.name,
                        "is_dir": entry.is_dir,
                    }
                )

        commits = []
        for relative in match.paths:
            commits.extend(recent_commits(root, relative))
        commits.sort(key=lambda c: c["when"], reverse=True)

        return {
            "project": asdict(match)
            | {"paths": list(match.paths), "blocked_by": list(match.blocked_by)},
            "blocks": [p.name for p in registry.projects if name in p.blocked_by],
            "commits": commits[:10],
            "files": files,
        }

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
