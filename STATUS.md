# Current status

[Start](README.md) · [Design](docs/design.md) · [Sources](docs/sources.md)

Updated **29 October 2026**. **Section 2 access checks are complete:** live SEC retrieval and an OpenRouter interpretation/critic pair passed. After recurring AAPL interpretation rejections, the existing no-digit rule is now included in the provider response schema and explained explicitly in the prompt. One AAPL pair passed with the fix; broad model reliability remains unmeasured. Your `.env` needs no changes.

The core goal is an inspectable research/discovery system whose source checks can correct claims and change candidate selection, with an evaluation of whether review helps. Four substantial workstreams remain: trustworthy evidence/calculations, broader company research, real corrections, and evaluation/release. A completion percentage would hide their unequal size. Wider automatic discovery and the original forecasting ambition follow as separate stages.

## Capability board

| Ready | Partial | Planned |
|---|---|---|
| Research, Discovery and History; optional model analysis | Narrow annual USD SEC facts | Archived filing/table evidence |
| Saved sources, Decimal metrics, replay/recovery, report names and archive/restore | Interpretation and critic checks | Real claim correction and re-screening |
| Five labelled synthetic examples | — | Held-out evaluation |
| Pass/fail/unknown screening; alphabetical selection | — | Separate statistical forecast |
| Connections: setup, current-session outcomes, explicit checks; live SEC and OpenRouter pair passed | — | Additional data feeds only when needed |

The saved 3% → 15% correction is synthetic. Current critic objections remain unresolved. Current SEC aggregates are not historical filing-vintage archives; forecast probabilities remain unavailable.

## Work checklist

- [x] **1 · Optional model analysis:** financial results complete independently; separate statuses, replay and submission recovery.
- [x] **2A · Connections status:** separate setup/attempt state, no secrets or automatic calls, safe refresh and restart behavior.
- [x] **2B · OpenRouter:** explicit server-only provider/model configuration, validated output, persisted usage and clear failures; automated checks use mocked providers, with a live attempt recorded below.
- [x] **2C · Explicit check controls:** fixed MSFT SEC probe without a model; saved-evidence model check with allowance, consent, provider-cap confirmation and submission recovery.
- [x] **Local setup:** load the optional project-root `.env`; existing environment variables take precedence.
- [x] **2C · Live SEC check:** real MSFT retrieval passed; annual revenue, operating income and margin were available. Original-table verification remains task 3.
- [x] **2C · Valid model pair:** interpretation and critic both passed using saved real SEC evidence and the existing configuration. Two calls, USD 0.001562316327; no automatic retries or model substitutions.
- [x] **Qualitative-output reliability fix:** publish the existing text restriction in the response schema; explain dates/filing names and allow digits in evidence IDs. One live pair on the user's saved AAPL evidence passed; original reports remain unchanged.
- [x] **Saved report organization:** name/reset name, archive/restore and separate history views; evidence and original research stay intact.
- [ ] **3 · Original filing evidence:** independently check two Microsoft FY2024 figures against the original annual filing/table and save the evidence packet.
- [ ] **4 · Fact/calculation validation:** reject incompatible issuer, unit, period and scope; preserve inputs and replay old reports.
- [ ] **5 · Broader searchable SEC US directory:** find a company outside the original five and show unsupported financial coverage explicitly.
- [ ] **6 · Selected-company financial screen:** screen up to ten user-selected companies with real retrieved financials; show pass/fail/unknown and actual coverage.
- [ ] **7 · Bounded correction:** version claims and objections, perform allowed follow-up checks, preserve unresolved cases, recompute affected values and re-screen candidates.
- [ ] **8 · Research evaluation and release:** freeze independently checked cases; compare deterministic, self-review and critic workflows for correctness, coverage, harmful revisions, cost and latency; package reproducible results and a runnable demo/report.
- [ ] **9 · Wider automatic discovery and evidence:** discover candidates across a declared broader universe; add filing events/material risks, prices or news only with dated evidence, coverage and access rights.
- [ ] **10 · Separate forecast baseline:** validate historical prices, adjustments and trading dates; freeze the SPY-relative target; compare chronological baselines, calibration and uncertainty; preserve forecasts independently from narrative review.

The five companies are the current supported live universe as well as the subjects of the synthetic fixtures. A broader directory adds identity lookup and search; directory metadata is not financial evidence or a ranking signal. Next is task 3. Implement 3–7 in dependency order; design evaluation cases in parallel, then run the frozen comparison. Stages 9–10 extend the core milestone. GP/neural/LLM factor mining, macro/global expansion, portfolio construction and execution remain optional later research.

For separate agent chats, use the [work-chat catalogue](docs/workstreams.md): C0–C10 cover current modules, remaining tasks, dependencies, acceptance checks and a copyable starter prompt. [Resource packs R0–R10](docs/sources.md#resource-packs-for-work-chats) map readings/data/tools to each chat. **Start with C0 baseline coordination, C1 task 3.1 (original filing evidence) and C5 task 8.1 (evaluation design).** C2's live connection checkpoint is complete; reopen it only for a concrete model failure or agreed provider/model change. Keep at most two implementation chats active beside integration; later lanes wait for their entry gates. Remaining assignments are planned; completed checkpoints are labelled in the catalogue. The final deadline, team capacity, experiment budget and forecast scope must be settled before a calendar estimate is meaningful.

**Inspect now:** restart Fieldnote and open History. Name a report, archive it, switch to Archived reports, then restore it. The original saved link and source evidence must remain readable. Live checks used an isolated store, so their outcomes will not appear as current-session status in a different running server.

The earlier MSFT model pair passed the output checks; its critic raised three unresolved source-support concerns. This verifies the connection and workflow, not research correctness. The earlier failed answer was not retained, so its exact rejection cause cannot be recovered. Rejection messages now distinguish unknown sources from forbidden numbers. Implementation and evaluation rules live in [Design](docs/design.md).

## Recorded checks

| Check | Result | Date |
|---|---|---|
| Live SEC probe | Passed; real annual MSFT financials available; run `fd04f247-b978-4dfb-8a3f-f3c02e258e9e` | 29 Oct |
| Live OpenRouter check | **Passed:** interpretation and critic validated; 3,914 tokens; provider-reported USD 0.001562316327; run `23499ae3-1805-4f59-8d28-315d9764d1fc` | 29 Oct |
| AAPL after schema/prompt fix | **Passed on first check:** interpretation and critic; 4,350 tokens; USD 0.001831508118; run `8060338f-11ca-4849-80bd-166da5061e85`; responses and copied evidence in `.tmp/aapl-qualitative-schema-9fc71b75/` | 29 Oct |
| Earlier model attempt | Answer rejected (`invalid_model_output`); critic skipped; 1,707 tokens; USD 0.0002402020269; run `194ef726-7671-41e3-bb8e-db5a76d5c5b4` | 29 Oct |
| Focused model/workflow regressions | 109 passed after the schema/prompt fix (37 model checks; 72 Connections/workflow tests); outgoing-schema check re-passed after tightening its assertion. One upstream Starlette/httpx deprecation warning | 29 Oct |
| Backend regression tests | 167 passed, including metadata persistence, legacy database compatibility, archive/replay and access-boundary checks; one upstream Starlette/httpx deprecation warning | 29 Oct |
| Browser scenarios | 23 section-2 scenarios previously passed; 2 focused desktop/mobile Connections checks re-passed after `.env` changes | 28 Oct |
| Report organization browser checks | 6 affected scenarios passed, including rename/archive/restore and failed-save retry; mobile accessibility and long-name/reset checks passed | 29 Oct |
| Production UI build | Passed | 29 Oct |
| Combined system/roadmap diagrams | Refreshed for section 2; artifact and desktop/mobile browser checks passed; captures visually inspected | 28 Oct |
| Research quality / investment performance | **Not validated** | — |

The successful model check and both response bodies are saved in `.tmp/2c-diagnosis-730aaa8d/`; the original SEC snapshot remains in `.tmp/2c-live-sec-model-20261028T183000Z/`. A preceding sandbox attempt could not resolve OpenRouter's hostname; the authorized network-enabled check above passed. UI checks use an isolated server/database on port 5173; their displayed provider outcomes are mocked. Earlier screenshots are in `.tmp/openrouter-verification/`; [tracked evidence](verification/evidence.json) remains available. No existing port-8000 server was stopped. The [dated review](docs/archive/alignment_review_2026-10-25.md) records earlier checks.
