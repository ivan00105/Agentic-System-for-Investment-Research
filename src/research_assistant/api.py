import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .application import Application
from .contracts import DomainError, Evidence, Run, RunRequest, UNIVERSE
from .fixtures import FIXTURE_CUTOFF, seed
from .store import Store

PROJECT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def instance_lock(path):
    # A second server must not mark the first server's active run as interrupted.
    handle = open(path, "a+b")
    try:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Another research server is already using this data directory.") from None
    try:
        yield
    finally:
        handle.close()


def create_app(data_dir: Path | None = None):
    root = data_dir or Path(os.getenv("RESEARCH_DATA_DIR", str(PROJECT / "data")))
    root.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        async with instance_lock(root / "server.lock"):
            store = Store(root)
            store.recover()
            seed(store)
            app.state.store = store
            app.state.application = Application(store)
            try:
                yield
            finally:
                app.state.application.close()

    app = FastAPI(title="Fieldnote Research", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origins = {"http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:5173"}
        if origin and origin not in allowed_origins:
            return JSONResponse({"error": {"code": "origin_denied", "message": "This local application does not accept requests from other websites."}}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": {"code": "origin_denied", "message": "Cross-site access is not allowed."}}, status_code=403)
        if request.method == "POST" and request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": {"code": "content_type", "message": "Send an application/json request."}}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        messages = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation", "message": " ".join(messages)}}, status_code=422)

    @app.get("/api/config")
    def config():
        connections = app.state.application.connections()
        return {"companies": [{"ticker": k, **v} for k, v in UNIVERSE.items()], "fixture_cutoff": FIXTURE_CUTOFF.isoformat(), "sec_configured": connections["sec"].configured, "model_configured": connections["model"].configured, "model": connections["model"].model, "forecast_available": False, "connections": connections}

    @app.post("/api/runs", response_model=Run, status_code=202)
    def submit(body: RunRequest, idempotency_key: str = Header(min_length=8, max_length=128)):
        return app.state.application.submit(body, idempotency_key)

    @app.get("/api/runs")
    def history(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        return app.state.store.history(limit, offset)

    @app.get("/api/runs/{run_id}", response_model=Run)
    def get_run(run_id: str):
        return app.state.store.get(run_id)

    @app.get("/api/runs/{run_id}/evidence/{evidence_id}", response_model=Evidence)
    def evidence(run_id: str, evidence_id: str):
        return app.state.store.evidence(run_id, evidence_id)

    dist = PROJECT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return JSONResponse({"error": {"code": "frontend_not_built", "message": "Build the frontend with npm run build, then restart the server."}}, status_code=503)
        return FileResponse(dist / "index.html")

    return app
