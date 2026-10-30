import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .contracts import Action, DomainError, Evidence, Report, Run, RunRequest, utcnow


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "snapshots").mkdir(exist_ok=True)
        self.path = root / "research.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                    request TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, stage TEXT NOT NULL, report TEXT, error TEXT,
                    synthetic INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs ((1))
                    WHERE status IN ('queued', 'running');
                CREATE TABLE IF NOT EXISTS actions (
                    run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL,
                    at TEXT NOT NULL, role TEXT NOT NULL, message TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (run_id, id)
                );
                CREATE TABLE IF NOT EXISTS run_metadata (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), label TEXT,
                    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1))
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def canonical(request: RunRequest):
        return json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def accept(self, request: RunRequest, key: str):
        payload = self.canonical(request)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id, request FROM runs WHERE idempotency_key=?", (key,)).fetchone()
            if old:
                # Older saved requests lack fields added with compatible defaults.
                if self.canonical(RunRequest.model_validate_json(old["request"])) != payload:
                    raise DomainError("This submission key was already used with different inputs.", "idempotency_conflict", 409)
                return old["id"], False
            active = db.execute("SELECT id FROM runs WHERE status IN ('queued','running')").fetchone()
            if active:
                raise DomainError("A research run is already active. Open History to follow it.", "run_active", 409)
            run_id = str(uuid4())
            now = utcnow().isoformat()
            db.execute("INSERT INTO runs (id,idempotency_key,request,status,created_at,updated_at,stage) VALUES (?,?,?,'queued',?,?,'Accepted')", (run_id, key, payload, now, now))
            return run_id, True

    def get(self, run_id: str) -> Run:
        with self.connect() as db:
            row = db.execute("SELECT runs.*, run_metadata.label, coalesce(run_metadata.archived,0) AS archived FROM runs LEFT JOIN run_metadata ON runs.id=run_metadata.run_id WHERE runs.id=?", (run_id,)).fetchone()
            if not row:
                raise DomainError("Run not found. Open History or start a new investigation.", "not_found", 404)
            actions = db.execute("SELECT sequence,at,role,message FROM actions WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        return Run(id=row["id"], request=RunRequest.model_validate_json(row["request"]), status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"], stage=row["stage"], actions=[Action(**dict(a)) for a in actions], report=Report.model_validate_json(row["report"]) if row["report"] else None, error=row["error"], synthetic=bool(row["synthetic"]), label=row["label"], archived=bool(row["archived"]))

    def history(self, limit: int = 30, offset: int = 0, archived: bool = False):
        with self.connect() as db:
            source = "FROM runs LEFT JOIN run_metadata ON runs.id=run_metadata.run_id WHERE coalesce(run_metadata.archived,0)=?"
            rows = db.execute(f"SELECT runs.id {source} ORDER BY runs.created_at DESC, runs.id LIMIT ? OFFSET ?", (int(archived), limit, offset)).fetchall()
            total = db.execute(f"SELECT count(*) {source}", (int(archived),)).fetchone()[0]
        # History deliberately excludes reports, evidence and action payloads.
        return {"items": [self.get(r["id"]).model_dump(mode="json", exclude={"report", "actions"}) for r in rows], "total": total}

    def set_metadata(self, run_id, patch):
        fields = patch.model_dump(exclude_unset=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
                raise DomainError("Run not found. Open History to choose a saved investigation.", "not_found", 404)
            db.execute("INSERT OR IGNORE INTO run_metadata (run_id) VALUES (?)", (run_id,))
            if "label" in fields:
                db.execute("UPDATE run_metadata SET label=? WHERE run_id=?", (fields["label"], run_id))
            if "archived" in fields:
                db.execute("UPDATE run_metadata SET archived=? WHERE run_id=?", (int(fields["archived"]), run_id))
        return self.get(run_id)

    def update(self, run_id: str, *, status=None, stage=None, report: Report | None = None, error=None):
        fields = {"updated_at": utcnow().isoformat()}
        for name, value in {"status": status, "stage": stage, "error": error}.items():
            if value is not None:
                fields[name] = value
        if report is not None:
            fields.update(report=report.model_dump_json(), synthetic=int(report.synthetic))
        with self.connect() as db:
            db.execute(f"UPDATE runs SET {','.join(k+'=?' for k in fields)} WHERE id=?", (*fields.values(), run_id))

    def action(self, run_id: str, role: str, message: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT coalesce(max(sequence),0)+1 FROM actions WHERE run_id=?", (run_id,)).fetchone()[0]
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?)", (run_id, seq, utcnow().isoformat(), role, message))
            db.execute("UPDATE runs SET stage=?, updated_at=? WHERE id=?", (message, utcnow().isoformat(), run_id))

    def add_evidence(self, run_id: str, evidence: Evidence):
        run = self.get(run_id)
        if evidence.available_at > run.request.cutoff:
            raise DomainError("Source is later than the research cutoff.", "ineligible_evidence")
        with self.connect() as db:
            old = db.execute("SELECT data FROM evidence WHERE run_id=? AND id=?", (run_id, evidence.id)).fetchone()
            data = evidence.model_dump_json()
            if old and old["data"] != data:
                raise DomainError("Evidence identifiers are immutable.")
            db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?)", (run_id, evidence.id, data))

    def evidence(self, run_id: str, evidence_id: str) -> Evidence:
        with self.connect() as db:
            row = db.execute("SELECT data FROM evidence WHERE run_id=? AND id=?", (run_id, evidence_id)).fetchone()
        if not row:
            raise DomainError("Evidence is unavailable for this run.", "not_found", 404)
        return Evidence.model_validate_json(row["data"])

    def all_evidence(self, run_id: str):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM evidence WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [Evidence.model_validate_json(r["data"]) for r in rows]

    def snapshot(self, payload: bytes):
        digest = hashlib.sha256(payload).hexdigest()
        target = self.root / "snapshots" / f"{digest}.json"
        if not target.exists():
            fd, name = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return digest

    def recover(self):
        with self.connect() as db:
            for row in db.execute("SELECT id, report FROM runs WHERE status IN ('queued','running') AND report IS NOT NULL").fetchall():
                report = Report.model_validate_json(row["report"])
                pending = [company for company in report.companies if company.review_status == "pending"]
                if pending:
                    for company in pending:
                        company.review_status = "failed"
                        company.review_error = "Model analysis was interrupted by a server restart. Start a new review explicitly."
                    db.execute("UPDATE runs SET report=? WHERE id=?", (report.model_dump_json(), row["id"]))
            db.execute("UPDATE runs SET status='interrupted', stage='Interrupted by server restart', error='The server stopped before this run finished. Saved results are preserved; start a new run explicitly.', updated_at=? WHERE status IN ('queued','running')", (utcnow().isoformat(),))
