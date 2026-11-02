import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .contracts import Action, Calculation, DomainError, Evidence, FinancialFact, Report, Run, RunRequest, UNIVERSE, utcnow


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
                CREATE TABLE IF NOT EXISTS financial_facts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calculations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
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
            if report is not None:
                self._financial_records(db, run_id, report)
            db.execute(f"UPDATE runs SET {','.join(k+'=?' for k in fields)} WHERE id=?", (*fields.values(), run_id))

    def _financial_records(self, db, run_id, report):
        from .financials import eligible_fact, identified, operating_margin
        from .filings import REVENUE_TAGS
        request = RunRequest.model_validate_json(db.execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        evidence = {e.id: e for e in self.all_evidence(run_id)}
        for company in report.companies:
            facts = {f.id: f for f in company.facts}
            if len(facts) != len(company.facts):
                raise DomainError("Financial fact identifiers must be unique.", "invalid_fact")
            for fact in facts.values():
                source = evidence.get(fact.evidence_id)
                if (identified(fact, "fact-").id != fact.id or source is None or source.packet is None
                        or fact.available_at > request.cutoff or source.snapshot_hash != fact.snapshot_hash
                        or source.packet.cik != fact.issuer_cik or fact.issuer_cik != UNIVERSE[company.ticker]["cik"]
                        or source.packet.accession != fact.accession or source.packet.form != fact.form
                        or source.packet.filed != fact.filed or source.packet.period_end != fact.end
                        or source.available_at != fact.available_at):
                    raise DomainError("Financial fact provenance is incompatible with this run.", "invalid_fact")
                self._immutable(db, "financial_facts", fact)
            calculations = {c.id: c for c in company.calculations}
            if len(calculations) != len(company.calculations):
                raise DomainError("Calculation identifiers must be unique.", "invalid_calculation")
            for calculation in calculations.values():
                if any(key not in facts for key in calculation.input_fact_ids):
                    raise DomainError("Calculation inputs must reference this report's immutable facts.", "invalid_calculation")
                inputs = [facts[key] for key in calculation.input_fact_ids]
                revenue = next((f for f in inputs if f.concept != "us-gaap:OperatingIncomeLoss"), None)
                income = next((f for f in inputs if f.concept == "us-gaap:OperatingIncomeLoss"), None)
                if operating_margin(revenue, income) != calculation:
                    raise DomainError("Calculation does not reproduce from its saved inputs and formula version.", "invalid_calculation")
                self._immutable(db, "calculations", calculation)
            for metric in company.metrics:
                if metric.fact_id is not None:
                    fact = facts.get(metric.fact_id)
                    if (fact is None or not eligible_fact(fact) or metric.value != fact.normalized_value
                            or metric.unit != "USD" or metric.period != f"{fact.start} – {fact.end}"
                            or fact.evidence_id not in metric.evidence_ids
                            or (metric.id == "revenue" and fact.concept not in {"us-gaap:" + tag for tag in REVENUE_TAGS})
                            or (metric.id == "operating_income" and fact.concept != "us-gaap:OperatingIncomeLoss")):
                        raise DomainError("Metric does not match its validated input fact.", "invalid_fact")
                if metric.calculation_id is not None:
                    calculation = calculations.get(metric.calculation_id)
                    if calculation is None or metric.value != calculation.result:
                        raise DomainError("Metric does not match its saved calculation.", "invalid_calculation")

    @staticmethod
    def _immutable(db, table, record):
        # table is a fixed internal name, never request data.
        saved = db.execute(f"SELECT data FROM {table} WHERE id=?", (record.id,)).fetchone()
        data = record.model_dump_json()
        if saved and saved["data"] != data:
            raise DomainError("Financial record identifiers are immutable.", "immutable_record", 409)
        db.execute(f"INSERT OR IGNORE INTO {table} VALUES (?,?)", (record.id, data))

    def fact(self, fact_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM financial_facts WHERE id=?", (fact_id,)).fetchone()
        if row is None:
            raise DomainError("Financial fact is unavailable.", "not_found", 404)
        return FinancialFact.model_validate_json(row["data"])

    def calculation(self, calculation_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM calculations WHERE id=?", (calculation_id,)).fetchone()
        if row is None:
            raise DomainError("Calculation is unavailable.", "not_found", 404)
        return Calculation.model_validate_json(row["data"])

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
        if evidence.packet:
            primary = [d for d in evidence.packet.documents if d.role == "filing"]
            if len(primary) != 1 or primary[0].snapshot_hash != evidence.snapshot_hash:
                raise DomainError("Filing packet does not identify its original source.", "source_integrity", 409)
            for document in evidence.packet.documents:
                if len(self.snapshot_bytes(document.snapshot_hash)) != document.byte_length:
                    raise DomainError("Filing packet source size does not match its saved bytes.", "source_integrity", 409)
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
        if target.exists() and target.read_bytes() != payload:
            raise DomainError("Saved source bytes failed their integrity check.", "source_integrity", 409)
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

    def snapshot_bytes(self, digest: str):
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise DomainError("Invalid source hash.", "not_found", 404)
        target = self.root / "snapshots" / f"{digest}.json"
        if not target.is_file():
            raise DomainError("Saved source bytes are unavailable.", "not_found", 404)
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise DomainError("Saved source bytes failed their integrity check.", "source_integrity", 409)
        return raw

    def recover(self):
        with self.connect() as db:
            for row in db.execute("SELECT id, report FROM runs WHERE status IN ('queued','running') AND report IS NOT NULL").fetchall():
                report = Report.model_validate_json(row["report"])
                pending = [company for company in report.companies if company.review_status == "pending"]
                if pending:
                    for company in pending:
                        company.review_status = "failed"
                        company.review_error = "Model analysis was interrupted by a server restart. Start a new review explicitly."
                    for call in report.model_calls:
                        if call.status == "running":
                            call.status = "incomplete"
                            call.error_code = "model_interrupted"
                    db.execute("UPDATE runs SET report=? WHERE id=?", (report.model_dump_json(), row["id"]))
            db.execute("UPDATE runs SET status='interrupted', stage='Interrupted by server restart', error='The server stopped before this run finished. Saved results are preserved; start a new run explicitly.', updated_at=? WHERE status IN ('queued','running')", (utcnow().isoformat(),))
