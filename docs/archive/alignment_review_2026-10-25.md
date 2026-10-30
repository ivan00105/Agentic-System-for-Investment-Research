> Archived on 27 October 2026. Historical design/review context; it may describe unimplemented behavior. For current guidance use [Start](../../README.md), [Status](../../STATUS.md), [Design](../design.md) and [Sources](../sources.md).

# Project alignment review — 25 October 2026

Completed 26 October 2026. Source checks and backend/browser regression checks were performed on 25 October; the final build and documentation checks were completed on 26 October.

The architecture remains appropriate. Keep the local React/FastAPI/Python/SQLite application and complete the evidence-and-correction research path before forecasting. There are enough external references; validated inputs and measured outcomes are the limiting work.

[STATUS.md](../../STATUS.md) owns the capability ledger and next acceptance criteria. This review records decisions and findings; it does not create a second roadmap. [Source audit](source_audit.md) contains the repository-by-repository and factor-family assessment.

## What the review covered

- Current source, contracts, tests, saved UI evidence, dependency manifests and all four local planning documents.
- Accessible history from **Plan and verify quant system** and **Branch · Project Topic Brainstorming**.
- Accessible portions of **Investment Research Project Sources investigation** and **Generate Architecture Diagrams**. Some ChatGPT assistant replies were content-reference placeholders; earlier diagram/proposal attachments were unavailable. Their contents were not independently verified.
- Current OpenBB announcement, OpenBQ site/licence and README-level checks of the supplied repositories. QuantStats appeared twice; there are 13 unique suggestions. This was not a full external code/security audit or performance replication.

The working product name remains Fieldnote. The project directory and existing Git repository remain unchanged. No source packages or plugins were installed.

## Architecture decisions

| Decision | Reason and boundary |
|---|---|
| Keep one local server and worker | Current scope is single-user research. Existing transactions, process locking and persisted request keys already protect runs. |
| Keep direct SEC integration | OpenBB is not a dependency. OpenBQ stewardship changes require documentation awareness, not a migration. |
| Make facts/calculations the next shared boundary | Facts must carry issuer, unit, period, scope, availability and original-source identity. A period string beside two numbers is insufficient for a general financial calculator. |
| Keep calculations and authorization in Python | Models propose claims/checks; host code owns evidence eligibility, allowed tools, arithmetic and budgets. Schema validity and model agreement do not establish truth. |
| Extend existing review control flow | Current interpretation/critic calls can become a bounded correction path. Five logical roles are a target responsibility map, not five new services or a course requirement. |
| Separate research support from forecast probability | Better prose or a corrected margin cannot change a statistical model's probability. Forecasting needs its own dated data and evaluation. |
| Keep saved-run compatibility | New contracts need additive defaults or explicit migrations. Replays preserve original results; new reviews preserve source evidence, not old review outcomes. |

Current execution has real safeguards: run-scoped evidence, immutable bytes, cutoff checks, no arbitrary model code execution, server-only credentials, loopback host/origin restrictions, persistent idempotency and explicit partial failures. Retain these through further work. Admission budgets are not hard remote-billing guarantees; in-flight calls can cross a time/token threshold.

### Architecture views

At review time, separate diagrams showed the architecture at commit `c11467888b9dcb1f4f6380d8cb3face288a7b27a` and a proposed correction workflow. They passed automated checks without perceptual visual review. On 28 October, those copies were superseded by the [current system and planned workflow overview](../../.archify/explainer-fieldnote-20261028-004223/fieldnote.html). The replacement describes a later working-tree snapshot, not that historical commit.

## Confirmed defects and fixes

**Revenue-tag recency.** The selector stopped at the first populated revenue taxonomy tag. A prior year's preferred tag could hide a newer eligible `Revenues` value and its matching income. Selection now compares all three supported tags before choosing the newest eligible period/filing. Equal duplicate values have deterministic tag preference; conflicting values for the same accession/period abstain. Issuer, USD, annual duration, cutoff and income matching checks remain. This does not establish universal accounting-concept equivalence.

**Obsolete review warnings.** New inference over saved evidence copied the previous report's entire limitation list. A successful review could therefore still say that review had not run. New reports retain source cautions separately in the additive `CompanyReport.source_limitations` field. The existing `limitations` field still includes everything relevant to the current report. `None` identifies legacy records; an empty list means no source cautions. New frozen runs migrate only exact known historical review messages, preserve unknown cautions and keep synthetic evidence labelled. Saved replay records are not rewritten.

## Remaining research gaps

- SEC company facts provide useful structured values, but current aggregates plus date filters do not reconstruct all information available at a historical cutoff. Save accession-specific original filing/table evidence and distinguish publication, reporting and retrieval times.
- Claims have a version number, but reviews do not target a version and no immutable dependency history exists. Every live critic objection currently remains unresolved. A recomputation alone never creates a revised claim.
- Discovery selects candidates before review. Once corrections can change inputs, recompute eligibility and bounded replacement using the same calculation/screening path. Unknown values must never pass.
- The qualitative-output digit check is a narrow guard: numbers written as words can pass. Future quantitative statements must reference host-owned facts/calculations rather than relying on textual number detection.
- No held-out comparison shows whether review improves correctness or harms correct claims. Use clean and erroneous cases, matched initial evidence/drafts, comparable budgets, coverage metrics and human assessment. Synthetic demonstrations are not evaluation results.
- No validated return forecast, price history pipeline or training artifact exists. A negative forecasting result is acceptable; inventing a probability is not.

## User-facing information policy

Show information when it helps a user understand the result or choose the next action. Keep implementation and reproducibility detail available without making it the main reading path.

| Keep visible | Place behind disclosure or in documentation |
|---|---|
| Company, result, reporting period and evidence cutoff | Raw run/evidence IDs, claim version numbers and record types |
| Synthetic status and whether a new review occurred | Hashes, raw source locators and detailed model/tool activity |
| Inspectable evidence and calculation inputs | Polling interval, worker/service design and idempotency mechanics |
| Material missing data, unresolved concerns, interpretation labels and partial failures | Environment-variable names and runtime setup commands |
| What changed, why it changed and supporting evidence | Full revision metadata and experiment configuration |

The UI uses **Open saved report**, **Review saved sources again**, and **Research with latest available sources**. Their existing replay/frozen/fresh semantics remain intact. Progress describes the current user task, while raw activity remains available in a collapsed detail area. The unavailable forecast is a short notice. Corrections and source dates remain inspectable; simplifying presentation must not remove uncertainty or imply verification.

## Resources and factors

OpenBQ's stewardship and the current Apache 2.0 platform licence are recorded in the [source audit](source_audit.md#openbb--openbq-awareness-required-migration-unnecessary). Workspace/FINOS plans, hosted offerings and the platform repository are separate. Nothing here needs a package migration.

Use FinanceToolkit for checked formula ideas, FinanceDatabase for possible later universe metadata, and TradingAgents/QuantMind/Vibe-Trading for selected provenance or workflow patterns. QuantStats fits a later defined return series. vnpy, QUANTAXIS and QuantDinger are broader trading platforms; the other collections are discovery or educational references. None proves a signal works or removes the need for local evaluation.

Fundamental metrics help explain and screen companies now. Technical price/volume features belong in the later small forecasting baseline. GP (genetic programming), neural-network and LLM factor mining remain separate later experiments. LLMs can extract cited, dated facts or propose hypotheses; deterministic code computes values and held-out tests assess prediction. Beta is market/factor exposure; alpha is residual performance relative to a specified risk model. Beating SPY alone does not establish risk-adjusted alpha.

## Verification and limits

The updated backend passes 24 tests, including cross-tag recency/conflict, legacy limitations, failed-to-successful frozen review, replay, source eligibility and request protection. The production frontend build passes. The upstream Starlette/httpx deprecation warning remains; it does not fail these checks.

All eight updated browser scenarios passed: seven in the full run and the remaining scenario after repairing a strict test selector. Checks cover accessible names, keyboard/focus, mobile layout, source disclosure, preserved partial results, refresh/idempotency, reconnect and hostile source text. Desktop and mobile screenshots were visually inspected. Screenshots from this review are in the ignored `.tmp/ui-review-verification/` directory; the original tracked verification evidence was preserved.

No authenticated provider call or paid model experiment was performed. Missing account/model configuration does not prevent fixture development, but it prevents claiming real-provider capability or research quality.
