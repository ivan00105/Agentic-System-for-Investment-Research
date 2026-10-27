# Current status

[Start](README.md) · [Design](docs/design.md) · [Sources](docs/sources.md)

Updated **28 October 2026**. Section 2B OpenRouter support and section 2C connection-check controls are implemented. **Setup only**, as requested: live checks are deferred; current verification uses mocked providers.

## Capability board

| Ready | Partial | Planned |
|---|---|---|
| Research, Discovery and History; optional model analysis | Narrow annual USD SEC facts | Archived filing/table evidence |
| Saved sources, Decimal metrics, replay and recovery | Interpretation and critic checks | Real claim correction and re-screening |
| Five labelled synthetic examples | Mocked provider verification | Live provider check and held-out evaluation |
| Pass/fail/unknown screening; alphabetical selection | — | Separate statistical forecast |
| Connections: setup, current-session outcomes and explicit test controls | Live SEC/model access unverified | Additional data feeds only when needed |

The saved 3% → 15% correction is synthetic. Current critic objections remain unresolved. Current SEC aggregates are not historical filing-vintage archives; forecast probabilities remain unavailable.

## Work checklist

- [x] **1 · Optional model analysis:** financial results complete independently; separate statuses, replay and submission recovery.
- [x] **2A · Connections status:** separate setup/attempt state, no secrets or automatic calls, safe refresh and restart behavior.
- [x] **2B · OpenRouter:** explicit server-only provider/model configuration, validated output, persisted usage and clear failures; mocked verification only.
- [x] **2C · Explicit check controls:** fixed MSFT SEC probe without a model; saved-evidence model check with allowance, consent, provider-cap confirmation and submission recovery.
- [ ] **2C · Real checks (deferred):** run the SEC probe and one interpretation/critic pair when requested, after identity, key, model and spending authorization are supplied.
- [ ] **3 · Original filing evidence:** independently check two Microsoft FY2024 figures against the original annual filing/table and save the evidence packet.
- [ ] **4 · Fact/calculation validation:** reject incompatible issuer, unit, period and scope; preserve inputs and replay old reports.
- [ ] **5 · Broader searchable SEC US directory:** find a company outside the original five and show unsupported financial coverage explicitly.
- [ ] **6 · Selected-company financial screen:** screen up to ten user-selected companies with real retrieved financials; show pass/fail/unknown and actual coverage.

The five companies are the current supported live universe as well as the subjects of the synthetic fixtures. A broader directory adds identity lookup and search; directory metadata is not financial evidence or a ranking signal. Tasks 3–6 are planned, not implemented. Task 3 can proceed while model access is pending. Later: bounded corrections and re-screening, frozen research comparison, wider automatic candidate sourcing, then a separate price forecast baseline. Add prices/news or other integrations only when that work needs them.

**Inspect now:** restart Fieldnote and open Connections. Setup and **Not tested** appear separately. Refresh status makes no provider calls; test buttons submit saved runs. The model test requires selected saved evidence, a positive allowance and consent/provider-cap confirmation. Reports expose per-call usage under Model usage; unknown costs remain unknown. Restart clears current-session outcomes, while saved runs retain their usage.

Live financial retrieval needs a real SEC contact identity. Model analysis also needs an accessible model and explicit experiment budget. Live access remains unverified. GP/neural-network/LLM factor mining and trading stay deferred. Implementation and evaluation rules live in [Design](docs/design.md).

## Recorded checks

| Check | Result | Date |
|---|---|---|
| Backend regression tests | 151 passed, including real SDK with mocked HTTP transport; one upstream Starlette/httpx deprecation warning | 28 Oct |
| Browser scenarios | 23 passed (18 full-suite scenarios plus 5 new recovery cases; existing lost-response case also re-passed); accessibility and desktop/mobile visual checks passed | 28 Oct |
| Production UI build | Passed | 28 Oct |
| Current/proposed diagrams | Automated checks passed; no perceptual visual review | 25–26 Oct |
| Live providers / research quality / investment performance | **Not validated** | — |

Current screenshots are in ignored `.tmp/openrouter-verification/`; [earlier tracked evidence](verification/evidence.json) remains available. Browser checks used an isolated server/database on port 5173, leaving port 8000 untouched. All provider responses and displayed connection outcomes in tests are mocked. Independent review caught two issues now fixed: invalid model output retains returned usage/cost, and malformed submission responses retain the original recovery key. The [dated review](docs/archive/alignment_review_2026-10-25.md) records earlier checks.
