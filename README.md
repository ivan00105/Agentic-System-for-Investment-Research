# Fieldnote — local stock research workspace

React + TypeScript + Vite, FastAPI, and SQLite. Research, discovery, evidence inspection, claim corrections, and saved run history live in one local browser application.

**The default demonstration is synthetic.** The five company names are real, but every bundled financial figure is invented for teaching. The Microsoft example deliberately corrects an annual/quarterly mismatch from 3% to 15%. It is a saved correction, not a live model performance claim.

## Project directory

Everything for this application lives in `stock_research/`, including `frontend/`, `src/`, `tests/`, local `data/`, `verification/`, and `docs/planning/`. Course materials remain in the parent directory.

The [implementation plan](docs/planning/implementation_plan.md), [technical blueprint](docs/planning/technical_blueprint.md), [source audit](docs/planning/source_audit.md), and [Codex build playbook](docs/planning/codex_build_playbook.md) are kept with the application.

## Start

Requires Python 3.12+ and Node 22.12+ (tested with Python 3.12 and Node 22). From this directory in PowerShell:

```powershell
.\start.ps1
```

The script creates a project virtual environment if needed, installs the pinned dependencies, builds the frontend, then serves [http://127.0.0.1:8000](http://127.0.0.1:8000). First setup needs internet access. Subsequent starts reuse the installed environment and build unless a manifest/source has changed. Leave that terminal running; press Ctrl+C to stop. It never exposes the server on your network. Only one server may own a data directory.

If PowerShell policy prevents local scripts, use these equivalent commands without changing your machine's policy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m research_assistant.cli
```

Open a saved replay to use the application with **no API credentials**. The default page opens the Microsoft teaching example. Discovery offers five synthetic companies with pass, fail and unknown outcomes.

## Optional real retrieval and new inference

Set the following environment variables in the terminal before starting the server. Do not put keys in frontend files, commit them, or paste them into a browser:

| Variable | Purpose |
|---|---|
| `SEC_USER_AGENT` | SEC contact identity, such as your application name and your real contact email |
| `OPENAI_API_KEY` | Your application API credential; Codex access does not supply this |
| `RESEARCH_MODEL` | An API model your account can access that supports Responses structured outputs |
| `RESEARCH_DATA_DIR` | Optional alternate local database/snapshot directory |

`.env` is ignored by version control but is **not automatically loaded**. Use actual environment variables. The SDK's `OPENAI_BASE_URL` may be used for a trusted compatible endpoint; gateway compatibility is not established by the mock tests.

- **Fresh retrieval + inference:** downloads SEC company-facts JSON, stores immutable bytes, selects annual USD revenue and operating income with matching accession and periods, then requests structured interpretation and critique. No price feed is configured.
- **New inference · frozen evidence:** copies the selected saved evidence and deterministic calculations, preserves the original company and cutoff, and invokes new interpretation/review. It does not copy old claims or old review outcomes. Synthetic evidence stays labelled synthetic.
- **Saved replay:** reopens the saved result without retrieval or inference. It works offline after installation. API replay requests can also create a saved copy with an explicit replay action.

When SEC configuration is missing, fresh retrieval fails clearly. When model configuration is missing or a model request fails, completed financial calculations remain available in a failed/partial run. The UI never substitutes synthetic data for live retrieval or silently replays a model result.

API capability has been tested with recorded/mocked SEC and model responses. **An authenticated live SEC/model smoke test is still required with your account and contact identity.** The default configuration does not make paid calls.

## Demo walkthrough

1. Open the Microsoft saved replay; read the synthetic-data banner.
2. Inspect Annual revenue and Operating income under **Inputs & source**.
3. Select **Evidence 1**. The source desk shows the excerpt, reporting period, availability and snapshot hash.
4. Follow the correction: draft 3% → mixed-period objection → aligned annual check → 15% revision.
5. Inspect the unavailable forecast and stated limitations. A margin is not an outperformance probability.
6. Open Discovery's teaching screen. NVIDIA remains **unknown**, Amazon fails the margin filter, and three candidates pass. Inspect a company, then return to the screen.
7. Open History and reopen the original report. Reloading or leaving the page does not create a run.
8. With no model configured, attempt frozen inference to demonstrate a clearly failed review with preserved financial results. This creates a new local run but no paid call.

## Implementation boundaries

| Component | Ownership |
|---|---|
| `frontend/src` | Presentation, accessible interactions, URL navigation, two-second status polling, stable submission retries |
| `api.py` | Validated HTTP boundary, local origin/host restrictions, static production assets |
| `application.py` | One worker, run lifecycle, shared discovery/research logic, bounded model review |
| `research.py` | SEC response validation, annual fact matching, deterministic Decimal calculations |
| `screening.py` | Pass/fail/unknown filters and declared selection order |
| `store.py` | SQLite transactions, idempotency, run-scoped evidence, content-addressed files |

SQLite's unique active-run index and an immediate write transaction protect against concurrent submissions. A process file lock prevents a second server from marking a live run interrupted. Each submission key is stored with its canonical request and result ID; a changed request with the same key is rejected. Accepted keys are retained for the database lifetime.

The browser retains an uncertain submission key in session storage, including across refresh, and retries that same intent. It never restarts research from a GET, rerender or reconnect. A server restart marks unfinished runs interrupted and preserves saved results. Graceful shutdown waits for the bounded worker; it does not cancel an already sent model request.

Budgets are shared across discovery: at most 12 model calls, 20 retrieval/check actions, a 180-second admission deadline, and an 18,000-token stopping threshold. Each company currently has one interpretation/critic pass (two calls, within the planned two-review-round maximum). Model requests have a 45-second timeout and no automatic retries; SEC requests have a 20-second read timeout, 5-second connect timeout and 25 MB response cap. In-flight calls can cross the admission deadline/token threshold; remote billing is not guaranteed exactly once. Costs are not estimated from invented prices. Token usage is logged.

## API

Interactive API documentation is available through the OpenAPI JSON at `/openapi.json`; the application uses a restrictive content security policy and does not rely on external Swagger assets.

| Endpoint | Behaviour |
|---|---|
| `GET /api/config` | Supported companies and configuration booleans; never credentials |
| `POST /api/runs` | JSON request plus `Idempotency-Key`; returns run with HTTP 202 |
| `GET /api/runs?limit=30&offset=0` | Paginated history |
| `GET /api/runs/{id}` | Persisted status, actions and available report |
| `GET /api/runs/{id}/evidence/{evidence_id}` | Run-scoped saved evidence; cross-run IDs return 404 |

Requests use a timezone-aware cutoff, a supported company or screen, and an explicit mode. Saved replay retains original inputs; frozen discovery may change screening thresholds over the same saved company packets. Supported screen fields are sector, minimum annual operating margin (ratio, so `0.1` means 10%), and limit 1–5. Invalid inputs return structured 422 errors; conflicts return 409; unsupported origins return 403.

## Verification and development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
# Stop a normally running server first; tests use port 8000 and a separate test database.
npm.cmd --prefix frontend test
```

Browser tests use an isolated installed Chrome profile, disable external credentials, check desktop/mobile with axe, and exercise replay, evidence, corrections, history, missing configuration, source injection, polling and an accepted submission whose HTTP response is lost. Screenshots are saved in `verification/`. Browser tests do not establish screen-reader usability or live-provider correctness on their own.

For frontend development, run the Python server and `npm.cmd --prefix frontend run dev` in separate terminals, then open port 5173. Vite proxies `/api` to port 8000. Production serves built assets from the Python server.

## Remaining research work

This implements the custom web milestone and a small functional backend foundation; the earlier full research specification remains a roadmap.

- No validated forecast artifact, historical price pipeline, model training or held-out statistical evaluation exists yet. Probability remains unavailable. Discovery explicitly selects alphabetically among eligible companies rather than pretending to rank by probability.
- Live facts use a current SEC aggregate, not archived filing-vintage data. Filing dates are conservatively available from the next midnight in America/New_York, converted to UTC. These safeguards do not establish leakage-free historical research. Annual mapping is intentionally narrow; quarterly metrics, events, free cash flow and general news are not implemented.
- The runtime is a bounded interpretation/critic workflow with deterministic checks, not the full five-role coordinator and correction/evaluation system. Critic objections remain unresolved pending adjudication. The saved synthetic correction demonstrates the UI contract, not measured agent accuracy.
- Public hosting, authentication, multi-user operation, cancellation and automatic checkpoint resumption are outside this local milestone. Do not expose this server publicly.

Back up the entire `data/` directory while the server is stopped; it contains the database and immutable snapshots. No destructive cleanup or reset endpoint is exposed.
