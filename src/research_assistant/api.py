import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import agent_api, companies_api
from .application import Application
from .config import WEB_DISCOVER_CONDITION, WEB_RESEARCH_CONDITION
from .contracts import ConnectionInfo, DomainError, Evidence, Run, RunMetadataPatch, RunRequest, UNIVERSE, utcnow
from .data import providers
from .data.errors import DataError
from .fixtures import FIXTURE_CUTOFF, seed
from .model_access import load_model_settings, load_model_sources
from .model_prefs import active_preferences, effective_model_settings, save_model_preferences
from .outlook_scheduler import OutlookScheduler
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
    load_dotenv(PROJECT / ".env", override=False, interpolate=False, encoding="utf-8-sig")
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
            app.state.agent_runs = agent_api.AgentRuns(root / "traces")
            app.state.outlook_scheduler = OutlookScheduler(store, root)
            app.state.outlook_scheduler.start()
            try:
                yield
            finally:
                app.state.outlook_scheduler.close()
                app.state.application.close()
                app.state.agent_runs.stop_all()

    app = FastAPI(title="Fieldnote Research", version="0.1.0", lifespan=lifespan)
    app.state.data_dir = root
    app.state.provider_checks = {}  # last live check per provider, for this server's lifetime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origins = {"http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:5173"}
        if origin and origin not in allowed_origins:
            return JSONResponse({"error": {"code": "origin_denied", "message": "This local application does not accept requests from other websites."}}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": {"code": "origin_denied", "message": "Cross-site access is not allowed."}}, status_code=403)
        if request.method in {"POST", "PATCH"} and request.headers.get("content-type", "").split(";")[0] != "application/json":
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

    def _config_payload():
        connections = app.state.application.connections()
        prefs = active_preferences(app.state.data_dir)
        effective = effective_model_settings(app.state.data_dir)
        sources = load_model_sources()
        default_source = prefs["default_source"] or "default"
        if prefs["default_source"]:
            connections = {**connections, "model": ConnectionInfo(
                configured=effective.configured, provider=effective.label, model=effective.model,
                configuration_error=effective.error, check=connections["model"].check,
            )}
        model_configured = effective.configured or any(s.configured for s in sources)
        return {
            "companies": [{"ticker": k, **v} for k, v in UNIVERSE.items()],
            "fixture_cutoff": FIXTURE_CUTOFF.isoformat(),
            "sec_configured": connections["sec"].configured,
            "model_configured": model_configured,
            "model": effective.model,
            "default_model_source": default_source,
            "default_agent_models": prefs["agent_models"],
            "model_sources": [
                {"id": s.id, "label": s.label, "provider": s.provider, "model": s.model, "configured": s.configured}
                for s in sources
            ],
            "forecast_available": False,
            "connections": connections,
            "agents": {"research": WEB_RESEARCH_CONDITION, "find": WEB_DISCOVER_CONDITION},
        }

    def _active_llm() -> str | None:
        prefs = active_preferences(app.state.data_dir)
        if prefs["default_source"]:
            return prefs["default_source"]
        primary = load_model_settings()
        return primary.provider if primary.configured else None

    @app.get("/api/config")
    def config():
        return _config_payload()

    @app.post("/api/config/models")
    def save_models(body: agent_api.ModelPreferences):
        save_model_preferences(app.state.data_dir, body.default_source, body.agent_models)
        return {**_config_payload(), "kinds": providers.status(app.state.provider_checks, default_llm=_active_llm())}

    @app.get("/api/outlook-log")
    def outlook_log():
        """Expose only the verified hash-chained live outlook log; no outlook number is recalculated here."""
        return {"entries": [entry.model_dump(mode="json") for entry in app.state.store.outlook_log()]}

    @app.get("/api/status")
    def data_status():
        """Every data provider by kind: tier, which settings are set (never their values), and the last check."""
        return {"kinds": providers.status(app.state.provider_checks, default_llm=_active_llm())}

    @app.post("/api/status/{name}/check")
    def check_provider(name: str):
        try:
            result = providers.run_check(name)
        except KeyError:
            raise DomainError("No provider with a live check has that name.", "not_found", 404) from None
        except DataError as exc:
            raise DomainError(str(exc), exc.code, 409) from None
        app.state.provider_checks[name] = {**result, "checked_at": utcnow().isoformat()}
        return {"kinds": providers.status(app.state.provider_checks, default_llm=_active_llm())}

    app.include_router(agent_api.router)
    app.include_router(companies_api.router)
    app.include_router(companies_api.universes)

    @app.post("/api/runs", response_model=Run, status_code=202)
    def submit(body: RunRequest, idempotency_key: str = Header(min_length=8, max_length=128)):
        return app.state.application.submit(body, idempotency_key)

    @app.get("/api/runs")
    def history(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), archived: bool = False):
        return app.state.store.history(limit, offset, archived)

    @app.patch("/api/runs/{run_id}", response_model=Run)
    def update_metadata(run_id: str, body: RunMetadataPatch):
        return app.state.store.set_metadata(run_id, body)

    @app.get("/api/runs/{run_id}", response_model=Run)
    def get_run(run_id: str):
        return app.state.store.get(run_id)

    @app.get("/api/runs/{run_id}/evidence/{evidence_id}", response_model=Evidence)
    def evidence(run_id: str, evidence_id: str):
        return app.state.store.evidence(run_id, evidence_id)

    @app.get("/api/runs/{run_id}/evidence/{evidence_id}/sources/{digest}")
    def evidence_source(run_id: str, evidence_id: str, digest: str):
        saved = app.state.store.evidence(run_id, evidence_id)
        allowed = {saved.snapshot_hash}
        if saved.packet:
            allowed.update(d.snapshot_hash for d in saved.packet.documents)
        if digest not in allowed:
            raise DomainError("Source is unavailable for this evidence.", "not_found", 404)
        return Response(app.state.store.snapshot_bytes(digest), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{digest}.bin"',
                                 "X-Content-Type-Options": "nosniff"})

    dist = PROJECT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return JSONResponse({"error": {"code": "frontend_not_built", "message": "Build the frontend with npm run build, then restart the server."}}, status_code=503)
        return FileResponse(dist / "index.html")

    return app
