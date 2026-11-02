# Current status

[Start](README.md) | [Design reference](docs/design.md) | [Detailed task briefs](docs/workstreams.md)

Updated **1 November 2026**. **Use this page to follow the MVP.** Read the detailed documents only when a step needs them. The user-selected scope includes company discovery and automatic claim correction; it extends beyond a single-company connection demo.

## MVP finish line

A user can find a supported SEC US company, select up to ten companies, retrieve inspectable annual financial evidence, calculate revenue/operating income/margin, request model interpretation and critic checks, apply corrections justified by saved sources or deterministic tools, and see the affected screen update. Save the original and revised results, sources, reasons, unresolved concerns and usage so the result can be reopened and replayed.

The first screen uses sector and annual operating margin. Automatic correction must have evidence of the change; uncertain narrative objections remain unresolved. Broader market scanning, news/events, price forecasting and factor research are later extensions. Backlog/Groma and additional diagrams are separate development-tool work, not prerequisites for this app path.

## Follow this order

| Order | Work | Finish when | Existing brief |
|---|---|---|---|
| **1 - Implemented; live check pending** | Fix model request limits, evidence input and failure reporting | Replace the universal hardcoded 2,000-token ceiling with an explicit model-appropriate output/reasoning policy. Remove silent 12,000-character table clipping; include the complete relevant table/context or report an input-context failure. Save the provider stop reason, reasoning usage and actual request settings; show running, incomplete and failed outcomes clearly. Preserve sources, financials and explicit control over retries. | C2 2C.4; coordinate shared changes through C0 0.2 |
| **2** | Accept the financial foundation and expose its proof in the UI | Review the original table/column/unit mapping independently; verify current contracts, old reports, replay and browser consumers. The user can inspect source dates, units and calculation inputs. Record acceptance and a feature-containing Git checkpoint before parallel runtime work. | C0 0.2; remaining C1 3.1 review; C6 U1 |
| **3** | Company search and selected-company Discovery | Search outside the original five companies; select 1-10 companies; retrieve their supported annual inputs and screen them. Unsupported coverage stays visible as unknown. Persist the selected universe and filter reasons. | C3 5.1-6.1; C6 U2 |
| **4** | Evidence-supported automatic claim correction | Define useful interpretation/critic tasks and versioned claims/objections. An objection triggers an allowed source/calculation check; record corrected, unchanged or unresolved with before/after evidence. Recompute dependent values when an input changes. | C4 7.1-7.2; C6 U3 |
| **5** | Re-screen after corrections | Re-run affected filters under the same selected universe; preserve why a candidate stayed, was excluded or was replaced. A real corrected case changes a result when the rule requires it. | C4 7.3 |
| **6** | Evaluate and deliver the complete path | Exercise correct, correctable, unsupported and incomplete cases; compare review conditions on frozen independently checked inputs and report harm, coverage, cost and failures. Verify browser behavior and clean setup/restore, then prepare the demo/report. | C5 8.1-8.3; C7 D1-D3; C0 0.3 |

Define evaluation cases/scoring and course submission requirements now; run the final comparison after the correction path exists. The [task catalogue](docs/workstreams.md#remaining-work-in-dependency-order) owns detailed acceptance criteria and assignments. This route does not claim those tasks have been dispatched or completed.

## What already works, and what is still provisional

- **Implemented:** the local app/API/store; optional model analysis; names/archive/restore; source snapshots and replay/recovery; accession-specific original-filing retrieval; typed facts and versioned Decimal calculations. C1 implementation has passed its recorded software checks; independent review and C0 acceptance remain open. [C1 handoff](docs/c1-handoff.md) | [integration record](docs/integration.md).
- **Current baseline:** five supported companies, sector/margin screening, alphabetical selection and one interpretation/critic pair. Objections currently stay unresolved. Discovery expansion, automatic correction and re-screening are still to implement.
- **Runtime policy fixed, 1 November:** removed the app output-token cap, total-token/time/call/tool quotas, 45-second model-timeout override, silent table clipping and arbitrary response length/count maxima. Calls use provider/model generation defaults and the SDK network timeout. Complete selected-table text is retained. Exact evidence/claim references, host-owned calculations, qualitative-only interpretations, one finite interpretation/critic pass, explicit retries and SEC download protection remain. Provider limits still apply; this is not a research-quality validation.
- **Demonstrations:** five labelled synthetic examples, including the Microsoft 3% to 15% correction. They do not demonstrate live correction quality. Live retrieval does not silently substitute them after failure.
- **Model checks:** earlier saved critic attempts ended at the former 2,000-token cap with `model_incomplete`; their missing stop reasons cannot be reconstructed. New calls distinguish running, output-limit, filtering and recognized input-context failures, retain provider status/reasoning usage and preserve financial results. Software checks cover these outcomes; no new live inference is claimed. Packaged prompt text remains unchanged and its research quality is unevaluated. A saved v2 Discovery run subsequently showed an AAPL critic response completed by the provider but rejected for an unsupplied claim/evidence reference. Schema v3 now supplies exact reference choices, clarifies their namespaces and retains rejected structured answers with specific failure messages. This change has offline proof; no new live inference is claimed.
- **Spending:** provider-side limits govern spending. As of 1 November the project no longer enforces its former USD allowance or provider-cap confirmation; legacy requests remain readable and reported usage/cost is still saved.

## Where to read only when needed

| Need | Owner |
|---|---|
| Run or configure the app | [README](README.md) |
| Choose the next product task | This page, then its brief in [Workstreams](docs/workstreams.md) |
| Understand stable behavior, trust rules or the workflow | [Design](docs/design.md); [workflow atlas](.archify/index.html) for diagrams |
| Check financial implementation and retained proof | [C1 handoff](docs/c1-handoff.md), [integration](docs/integration.md), `verification/` |
| Choose external data, tools or research references | [Sources](docs/sources.md) |
| Revisit the separate development-panel proposal | [Development-tool plan](tasks/plan.md), [its checklist](tasks/todo.md); not installed or migrated |
| Inspect earlier proposals | `docs/archive/`; reference history, not the current work order |

## Recorded checks

1 November critic-reference checks: **201 backend tests passed**, production build passed, and the focused browser/accessibility check passed. Exact reference choices, namespace mix-ups, invalid-ID rejection, retained rejected answers and visible failure messages are covered. [Check record](verification/integration/critic-references-20261101.json). No new live inference.

1 November runtime-policy checks: **198 backend tests passed**, production build passed, and one focused browser/accessibility scenario passed (provider-default limit, stop reason, reasoning usage and Running-to-incomplete transition). [Check record](verification/integration/model-policy-20261101.json). Provider outcomes were mocked; no new live inference or research-quality claim.

| Check | Result | Date |
|---|---|---|
| Provider-side spending control | Removed project USD allowance/cap confirmation; usage recording, request recovery and execution limits preserved. **81 focused backend tests**, **11 browser checks** and production build passed; desktop/mobile captures inspected. All provider calls mocked | 1 Nov |
| Live SEC probe | Passed; real annual MSFT financials available; run `fd04f247-b978-4dfb-8a3f-f3c02e258e9e` | 29 Oct |
| Live OpenRouter check | **Passed:** interpretation and critic validated; 3,914 tokens; provider-reported USD 0.001562316327; run `23499ae3-1805-4f59-8d28-315d9764d1fc` | 29 Oct |
| AAPL after schema/prompt fix | **Passed on first check:** interpretation and critic; 4,350 tokens; USD 0.001831508118; run `8060338f-11ca-4849-80bd-166da5061e85`; responses and copied evidence in `.tmp/aapl-qualitative-schema-9fc71b75/` | 29 Oct |
| Earlier model attempt | Answer rejected (`invalid_model_output`); critic skipped; 1,707 tokens; USD 0.0002402020269; run `194ef726-7671-41e3-bb8e-db5a76d5c5b4` | 29 Oct |
| Focused model/workflow regressions | 109 passed after the schema/prompt fix (37 model checks; 72 Connections/workflow tests); outgoing-schema check re-passed after tightening its assertion. One upstream Starlette/httpx deprecation warning | 29 Oct |
| Backend regression tests | **195 passed** at the C0 checkpoint, including C1 packet/fact/calculation and legacy/replay coverage; one upstream Starlette/httpx deprecation warning. Earlier 29 Oct baseline: 167 passed | 31 Oct |
| C1 original packet and runtime records | Saved-source checks passed; MSFT FY2024 margin reproduced as **44.6443%**. [Packet](verification/packets/msft-fy2024/20261029T182734Z/README.md), [runtime case](verification/c1-runtime.json), [C0 check record](verification/integration/checks-20261031.json). Separate-person review remains pending | 30 Oct; rechecked 31 Oct |
| Browser scenarios | 23 section-2 scenarios previously passed; 2 focused desktop/mobile Connections checks re-passed after `.env` changes | 28 Oct |
| Report organization browser checks | 6 affected scenarios passed, including rename/archive/restore and failed-save retry; mobile accessibility and long-name/reset checks passed | 29 Oct |
| Production UI build | Passed again at the C0 checkpoint; does not establish C6 U1 browser behavior | 31 Oct |
| Combined system/roadmap diagrams | Refreshed for section 2; artifact and desktop/mobile browser checks passed; captures visually inspected | 28 Oct |
| Research quality / investment performance | **Not validated** | — |

The successful model check and both response bodies are saved in `.tmp/2c-diagnosis-730aaa8d/`; the original SEC snapshot remains in `.tmp/2c-live-sec-model-20261028T183000Z/`. A preceding sandbox attempt could not resolve OpenRouter's hostname; the authorized network-enabled check above passed. UI checks use an isolated server/database on port 5173; their displayed provider outcomes are mocked. Earlier screenshots are in `.tmp/openrouter-verification/`; [tracked evidence](verification/evidence.json) remains available. No existing port-8000 server was stopped. The [dated review](docs/archive/alignment_review_2026-10-25.md) records earlier checks.
