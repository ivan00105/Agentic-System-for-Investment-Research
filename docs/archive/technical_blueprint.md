> Archived on 27 October 2026. Historical design/review context; it may describe unimplemented behavior. For current guidance use [Start](../../README.md), [Status](../../STATUS.md), [Design](../design.md) and [Sources](../sources.md).

# Technical blueprint: from specification to running application

19 October 2026. This supplements the [implementation plan](./implementation_plan.md). It specifies proposed interfaces and implementation behavior; snippets are design examples, not a delivered or tested application. The [Codex build playbook](./codex_build_playbook.md) describes task prompts, models, effort levels and development order.

Custom-web implementation update: [Fieldnote](../../README.md) now implements the frontend, HTTP/run lifecycle, evidence store, labelled synthetic demonstrations and a narrow live-data/model integration path. The remaining research modules below are still proposed; their presence in this specification is not a claim of implementation. Forecasting and the full multi-role evaluation remain unavailable. The frontend design contract and verification evidence are under `stock_research/verification/`.

25 October: follow [STATUS.md](../../STATUS.md) for capability and milestone order, and the [alignment review](alignment_review_2026-10-25.md) for current decisions. Extend the present modules when the next invariant needs them; the module table below is a target responsibility map, not an instruction to scaffold each file. The existing Responses integration already supports mocked tests; actual provider access remains unverified.

## 1. Concrete technology choices

Build one local Python application in the dedicated `stock_research` project directory, separate from course exercises. The implemented foundation uses Python 3.12, a virtual environment with a pinned requirements file, Pydantic v2, httpx, SQLite, FastAPI and Uvicorn. Its custom browser interface uses React, TypeScript, Vite and ordinary CSS with an npm lockfile. Beautiful Soup, pandas/NumPy, scikit-learn and exchange_calendars remain future dependencies for their corresponding research stages; do not install speculative components.

Use the official OpenAI Python SDK and Responses API if the chosen account supports them. A university gateway may expose different endpoints/models: test the actual gateway before selecting the runtime model. Keep that integration in one `llm.py` module. Do not build a provider framework in anticipation of switching.

Use standard-library Decimal, datetime, hashlib, JSON, SQLite, argparse and pathlib. The implemented layer stores UTC timestamps and uses IANA timezone data (tzdata on Windows) to interpret SEC filing dates in America/New_York. Use pytest for invariant/API tests and Playwright with axe for browser checks. The production FastAPI server serves the built React assets under the same origin. No Redis, Celery, vector database or Docker is needed.

## 2. Modules and interfaces

The interfaces below are the target boundaries, not a request to scaffold empty files in advance. Implement a module when its first real caller exists.

| Module | Functions/data it owns | First acceptance case |
|---|---|---|
| `contracts.py` | Validated requests, facts, calculations, claims, objections and reports | Invalid units/unknown fields/naive datetimes are rejected |
| `data/identity.py` | `resolve_security(ticker, universe)` | One supported listing maps to a reviewed issuer; unsupported/ambiguous input fails clearly |
| `data/sec.py` | Retrieve submissions, eligible filings and original content | Later amendment is excluded at an earlier cutoff |
| `data/store.py` | Immutable payloads, metadata, run/action persistence | Same payload is deduplicated; different source versions remain distinct |
| `data/filings.py` | Parse sections, tables and fact candidates | Source text/cells can be reopened from an evidence ID |
| `data/prices.py` | Normalize one provider's bars/actions | Split/dividend fixture matches a hand calculation |
| `tools/facts.py` | `select_fact(query, trusted_context)` | Annual versus quarterly ambiguity returns a typed issue |
| `tools/metrics.py` | `calculate_metric(name, input_ids, trusted_context)` | Correct inputs produce traceable output; incompatible inputs fail |
| `tools/retrieval.py` | `search_evidence(query, trusted_context)` | Every returned source is eligible for the run's cutoff |
| `forecast/features.py` | Price features as of a cutoff | Appending future prices does not change past features |
| `forecast/labels.py` | Anchor/end session and outcome calculation | Exactly 20 return intervals, including holiday boundaries |
| `forecast/train.py` | Chronological fitting and model manifest | No training outcome matures after the training cutoff |
| `forecast/predict.py` | Load approved artifact and produce immutable `p0` | Missing/invalid features cannot become a fabricated prediction |
| `llm.py` | SDK calls, role configuration, structured parsing and usage | Refusal, timeout and malformed output become explicit outcomes |
| `agents/` | Coordinator, filings, events, quant and critic instructions | Roles return typed proposals referencing existing records |
| `workflow.py` | Transitions, budgets and tool authorization | Repeated requests terminate; budget exhaustion never means approval |
| `review.py` | Claim versions, objection dispositions, dependency invalidation | Correcting a fact invalidates its dependent calculations/claims |
| `discovery.py` | Screen specification, three-valued filters and candidate queue | Unknown filter input cannot pass; rejected candidate is replaced within cap |
| `reporting.py` | Final validated report, citations and numeric rendering | Report displays stored numeric values and resolvable citations |
| `application.py` | `run_research(request)` / `run_discovery(request)` | UI and CLI produce equivalent core results |
| `frontend/`, `api.py`, `cli.py` | Input/output, validated submission and server startup | Refresh, rerender and ambiguous HTTP retries never duplicate a run |
| `evaluation/` | Frozen manifests, scoring and comparisons | Same saved forecast cases produce the same numeric scores |

## 3. Domain records: make ambiguity explicit

Use Pydantic for boundary validation and ordinary immutable records where useful internally. Money/fact values use Decimal; model features use finite floats after explicit conversion. Store Decimal as canonical strings in JSON to avoid hidden precision changes. Preserve raw values as well as normalized values.

Example core shape:

```python
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_id: str
    issuer_id: str
    concept: str
    taxonomy_tag: str
    value: Decimal
    unit: str
    scale: int
    period_kind: Literal["instant", "duration"]
    period_start: date | None
    period_end: date
    accounting_basis: str
    scope: str
    accession: str
    available_at: AwareDatetime
    evidence_id: str

class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str
    kind: Literal["fact", "calculation", "interpretation"]
    evidence_ids: list[str]
    calculation_ids: list[str]
    materiality: Literal["central", "supporting", "minor"]

class ObjectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    claim_version: int = Field(ge=1)
    issue: Literal["period", "unit", "entity", "calculation",
                   "unsupported", "contradicted", "missing_risk"]
    explanation: str
    evidence_ids: list[str]
    requested_check: str | None

class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objections: list[ObjectionDraft]
```

Additional validators must enforce period ordering, finite values, supported units/scales and the instant/duration relationship. Cross-record checks happen in the host application: IDs exist, belong to the correct run/entity, satisfy the cutoff, and support the requested operation. A Pydantic schema does not establish those relationships or semantic truth.

The model proposes claim content and objections. The host assigns IDs/versions and stores verification results. Do not let model output assign itself a `verified=true` field or replace a source's availability timestamp.

Refine status modeling from the earlier plan into separate fields:

- Run: queued/running/completed/failed/cancelled/budget_exhausted.
- Report support: supported/qualified/abstained, with reasons.
- Forecast availability: available/unavailable/missed_issue_deadline.
- Forecast resolution: pending/resolved/unmeasurable.
- Candidate eligibility: pass/fail/unknown.

“Completed” is an operational fact. It does not mean supported, correct or profitable.

## 4. Storage and retrieval implementation

Use one SQLite database and a local payload directory. Logical tables: securities, source_snapshots, evidence_spans, facts, calculations, runs, actions, claim_versions, objections, forecasts and forecast_outcomes. Use foreign keys and indexes on issuer, availability, run ID and claim ID/version. Start with one schema; introduce versioned migrations when the schema actually changes.

Write downloaded content to a temporary file, compute its hash, then atomically rename it into a content-addressed location. Store source metadata separately: identical bytes can appear at different URLs/times. Do not use the content hash alone as the identity of a publication event.

Use SQLite WAL where supported, a busy timeout, short transactions and one authoritative writer per run. Never hold a database transaction across an HTTP/LLM call. Reserve an action and budget transactionally, execute outside the transaction, then persist the result. Associate every tool result with its action ID.

A timed-out model request may have executed and incurred cost. Record uncertainty and retry conservatively; local deduplication cannot guarantee exactly-once remote billing. Interrupted writes must not produce a half-valid report. Initially mark interrupted runs clearly and permit a clean rerun; sophisticated checkpoint resume is a later enhancement.

Parse filing HTML into headings, paragraphs and tables while preserving identifiers and original content. Prefer section/table boundaries over arbitrary fixed-size chunks. Keep table headers with cells. Remove executable HTML; render only sanitized content.

Create a SQLite FTS5 index over extracted text after checking FTS5 availability. Search must apply entity, source-version and availability restrictions to the candidate set **before** selecting top-k; retrieving future chunks and dropping them afterward can distort retrieval. If FTS5 is unavailable, a small bounded local text search is sufficient for the first five issuers. Query expansion must not broaden the temporal boundary.

Every citation resolves to a stored span plus original URL, filing accession, section/table locator and availability date. Do not invent PDF page numbers for HTML filings.

## 5. Deterministic facts and calculations

Implement one fact-selection policy. Given issuer, concept, period specification and cutoff:

1. Restrict to eligible source versions and matching issuer.
2. Select candidates by taxonomy mapping, scope, unit, period kind/start/end and accounting basis.
3. Resolve duplicate observations using an explicit version policy among eligible filings.
4. If multiple incompatible values remain, return `ambiguous` with candidate IDs. The agent can inspect evidence; it cannot silently choose the most convenient value.
5. Return a fact ID, normalized value and provenance.

For example, `operating_margin` accepts operating-income and revenue fact IDs. The calculation function independently checks issuer, exact period alignment, currency/basis/scope, available-at constraints and a positive revenue denominator before computing `income / revenue`. It returns a Calculation record containing the formula version and both input IDs. Rounding is a presentation step.

A first synthetic fixture can use revenue=100 million and operating income=15 million for the same year. Expected margin is 0.15, displayed as 15.0%. A quarterly numerator against annual revenue must fail. Label this synthetic fixture; add a separately hand-checked real filing fixture before calling the data path complete.

A first report can be a deterministic template containing only these values and references. This establishes the reliable path on which the agents depend.

## 6. Implementing an application agent

An application agent is a role instruction, a bounded context, allowed tools, a model invocation and validated output. It is not a separate process or a separately trained model. One API model can play all five roles through separate calls.

Use trusted host context containing run ID, issuer, cutoff and allowed evidence IDs. Tools get this context from the application, not from model arguments. A model asking for a later cutoff cannot change it.

Example tool boundary:

```python
# Proposed interface; implementation belongs in tools/metrics.py.
def calculate_metric(
    metric: str,
    input_fact_ids: list[str],
    *,
    context: RunContext,  # supplied only by the host
) -> CalculationResult:
    ...
```

Expose a fixed registry of named, validated functions. The SDK returns a tool-call name and argument payload; the host validates them, checks policy/budget, runs the function and sends a result tied to the call ID. Never dispatch with `eval`, dynamic imports, model-generated SQL or model-generated Python.

For the OpenAI path, use Responses function calling with explicit strict schemas. Function calling chooses an operation; structured output shapes a final report/critique. These serve different purposes. The official [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling) describes the call/result cycle and strict-schema requirements. Schema adherence still does not validate factual claims.

An illustrative structured critique call:

```python
response = client.responses.parse(
    model="gpt-6.1-sol",
    reasoning={"effort": "medium"},
    instructions=CRITIC_INSTRUCTIONS,
    input=serialized_draft_and_eligible_evidence,
    text_format=Critique,
    store=False,
)
```

The production wrapper must check completion status, refusal, parsing failure, usage, timeouts and record membership before consuming `output_parsed`. A refusal or incomplete result is a typed failure, not an empty objection list. A legitimately completed `objections=[]` means no objection was identified. [Structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

Do not assume unsupported API parameters work through an HKU gateway. Run a tiny capability check for the actual endpoint/model: text response, tool call/result, structured result, supported effort and error format. Keep credentials in environment variables, outside source control. Do not copy Codex login credentials into the application.

### Role contracts

| Role | Receives | May do | Returns |
|---|---|---|---|
| Coordinator | Request, current claim/task state, missing items, budget | Select allowed specialist/tool/finalization action | Next action with a concise justification tied to an unresolved item |
| Filings | Issuer, requested concepts/periods, eligible filing index | Search/inspect relevant sources and request facts | Evidence/fact references and comparability issues |
| Events | Eligible event material and research question | Identify events, distinguish facts from management forecasts | Dated event claims, citations and uncertainty |
| Quant | Available facts/features/model output | Select named calculations, interpret results | Calculation references and explicitly model-attributed forecast explanation |
| Critic | Claim versions, evidence and calculations | Identify a concrete objection or request a check | Zero or more claim-specific objections |

Context should contain relevant structured records and short evidence spans, not all raw filings or every past agent message. Include contradictory evidence rather than truncating it to favor the draft. Use a deterministic size limit and log which evidence was supplied.

## 7. Workflow logic

Use a loop with typed actions and a single state owner. The following is control-flow pseudocode, not executable application code:

```text
validate request and freeze trusted context
load or retrieve eligible inputs
initialize unresolved requirements and action budgets

while operational limits permit:
    choose allowed actions for the current state
    ask coordinator for one action
    validate action, arguments and referenced IDs
    reserve budget; execute tool/specialist; record outcome
    update facts, calculations, claims and unresolved requirements

    when draft is ready:
        request critic review if configured and rounds remain
        record objections; choose targeted follow-up or disposition

    when coordinator requests finalization:
        run host finalization checks
        if checks fail: return explicit missing requirements to coordinator
        otherwise: produce supported/qualified/abstained report and stop

on exhaustion or failure:
    retain completed evidence and objections
    produce an explicitly incomplete/qualified result where possible
```

Agentic behavior is the conditional choice of the next useful action. The host owns hard restrictions. Repeated identical unsuccessful actions should be recognized using an action fingerprint containing arguments, cutoff and source versions. A materially changed evidence version can justify rerunning a check.

Do not require a critic round to close every objection. If a central issue cannot be resolved within limits, preserve it and abstain from that conclusion. Corrections create new records; a dependency walk invalidates affected calculations and claims. A final template inserts numeric values from those records so narrative generation cannot quietly change 15% to 50%.

## 8. Forecast and discovery implementation

Implement forecast training as an explicit offline command. A research request loads a versioned model artifact; it never tunes or retrains a model based on the current requested result. Persist feature names/order, transformation state, target version, training cutoff, last admitted label end, universe version, code version and dependency lock hash. Only load model files created by the project; do not deserialize untrusted pickle/joblib artifacts.

The feature matrix has one row per security/cutoff. Labels live in an evaluation-only dataset. Prediction code cannot retrieve labels. All preprocessing fits on the training partition. Enforce the label-maturity and calendar rules in the main plan, and test that adding future rows cannot change earlier features or predictions from a fixed model.

Keep the existing target convention: a fixed post-close information cutoff, next-session closing anchor, and 20 close-to-close intervals after that anchor. Use exchange sessions and timezone-aware timestamps, not business-day offsets alone. Preserve the original probability and issue deadline; collect outcomes later without editing it.

Discovery calls deterministic `screen_universe` and `rank_candidates`, then invokes the same `run_research` implementation for each selected candidate. Parent discovery state owns the total budget; child research budgets cannot multiply spending without limit. Ranking is `p0` descending among eligible candidates with available predictions, with a stable tie-breaker. Research findings may invalidate eligibility, but prose cannot silently modify `p0`.

## 9. Interface and operational behavior

The current implementation starts with `stock_research/start.ps1`, serving the custom React workspace and API at `http://127.0.0.1:8000`. It includes Research, Discovery and History, an adjacent evidence inspector (inline on mobile), preserved original/objection/check/revision steps, and clearly distinct fresh/frozen/replay modes. Future research CLI commands below remain acceptance targets, not existing commands:

```text
uv run research-assistant demo --fixture margin_valid
uv run research-assistant research --ticker MSFT --cutoff <ISO8601>
uv run research-assistant discover --screen <screen.json> --cutoff <ISO8601>
uv run research-assistant train --manifest <training.json>
uv run research-assistant evaluate --manifest <heldout.json>
```

The application functions run in one background worker. Validate and persist the request before execution; one active-run index and a process lock enforce local ownership. `POST /api/runs` requires a durable idempotency key; changed payloads under an existing key fail. GET endpoints provide paginated history, run status/report, and run-scoped evidence. The frontend keeps the run ID in the URL, retains uncertain submission intents across refresh, and polls every two seconds while active. A restart marks unfinished runs interrupted without automatic retry. Cancellation and checkpoint resumption are not implemented. SDK and retrieval timeouts bound individual external operations.

Show results, periods, sources, calculation inputs, objections and qualifications first. Use plain action labels for fresh research, reviewing saved sources again and opening a saved report. Keep technical provenance and action/usage history behind disclosure; setup commands and implementation details belong in documentation. Preserve explicit unavailable forecasts and actionable errors without raw credential or request details.

## 10. Proof and handover

For each completed increment, require: the actual command run, exit/result summary, a saved sample output, and remaining limitations. Test core invariants with fixtures that do not require network access. Keep opt-in live-provider smoke tests separate. A unit test of a mocked SDK does not establish that an account can access the selected model.

Before the final demonstration, another group member should install from the lockfile and run the fixture demo using only the README. Then run a small live model/provider smoke test with the team's actual account. Record model IDs, effort, source hashes, prompts, target version and actual usage in every evaluation artifact.

The local web foundation already exceeds the original fixture-CLI starting point. The next deliverable is one independently checked annual source packet with typed facts/calculations, followed by a bounded correction path and research evaluation. Forecasting comes afterward; do not rebuild the existing interface or initialization scaffolding.
