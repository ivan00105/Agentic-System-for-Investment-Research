# C0 integration baseline and ownership

Recorded **31 October 2026**, Asia/Hong_Kong. Owner: this chat, **Establish Fieldnote integration baseline** (`01a18ae2-4d04-75c3-8d32-6871dcee2261`). Task **0.1 is complete**. C1 implementation is also complete; separate-person packet review and feature acceptance at **0.2** remain open.

## Shared baseline

- Repository: `D:\HKU\COMP7608_Large_language_models\stock_research`.
- Committed base: `2c7f20378ae0667d9d3336758854234e9cacf211`, branch `ivan`, aligned with the locally recorded `origin/ivan` (0 ahead/behind; no remote fetch performed).
- One worktree exists: this checkout. Initial state: **0 staged, 9 modified tracked files, 26 untracked files** (35 files, 49,757,931 bytes). No clean feature baseline is claimed.
- [Baseline manifest](../verification/integration/baseline-20261031-9b62d98b.json) records exact paths, hashes, status and index fingerprint. Byte copies, index copy and binary staged/unstaged patches are in `.tmp/c0/20261031-9b62d98b/`. This is a local recovery copy; `.tmp` is ignored and is not a portable handoff.
- The committed base plus that manifest identifies the current **dirty integration candidate**. A worktree at the committed base does **not** contain C1's pending code, tests or packet. Runtime consumers must wait for an accepted committed C1 checkpoint, or an explicitly coordinated equivalent transfer.
- No staging, commits, resets, cleans, stashes, moves, server stops or new worktrees were performed for 0.1. Existing ignored credentials, stores and experiments stay in place; credentials were not read or copied.

## Work found and ownership

Chat state was inspected through the app, not inferred from file timestamps. `notLoaded` is an app state and does not prove that no external editor or process exists. No listener was returned for ports 8000/5173 during the read-only port check; that is a point-in-time observation, not permission to stop a future listener.

| Lane / task | Observed work and responsible chat | File ownership / next gate |
|---|---|---|
| C0 / 0.1 | This chat owns integration, the baseline and assignments. | `STATUS.md`, `docs/workstreams.md`, `docs/integration.md`, `verification/integration/`; coordinates all shared-file changes. |
| C1 / 3.1 | Packet delivered by **Verify Microsoft FY2024 evidence** (`01a188e4-7e71-7a62-adca-66ee58cfe237`); latest turn completed, app state `notLoaded`. Separate-person review is pending. | Preserve `verification/packets/msft-fy2024/20261029T182734Z/` as the sealed input; never edit it to make checks pass. |
| C1 / 3.2, 4.1, 4.2 | **Implementation complete; maintenance only.** All changes remain uncommitted. [Handoff](c1-handoff.md) and [runtime evidence](../verification/c1-runtime.json) exist. C0 acceptance is pending. | C1 owns `filings.py`, `financials.py`, the pending `research.py` changes, `tests/sec_fixture.py`, `tests/test_filing_packets.py`, `tests/test_financial_records.py`, existing changes in `tests/test_connections.py` and `tests/test_system.py`, `docs/c1-handoff.md`, `verification/c1-runtime.json`. |
| C1 shared-file overlay | Already supplied by C1; preserve as found. | Pending edits to `contracts.py`, `store.py`, `api.py`, `application.py`, `docs/design.md` and `docs/sources.md` belong to this C1 handoff. C0 controls the next edit/integration window; no second writer while they are pending. |
| Duplicate C1 chat | **Verify Microsoft FY2024 10-K** (`01a188e3-c2e5-7fd2-8176-b8c66b1fdea1`) has only an interrupted initial turn; app state `notLoaded`. | No independent implementation or file claim found. Do not assign a second C1 implementation to it. |
| C2 | Connection checkpoint complete; no current task assigned. | Reopen only for a reproducible concrete failure or agreed provider/model change. |
| C5 / 8.1 | Ready to assign; no executing owner identified. | Reserve a new `docs/evaluation-protocol.md` and case-matrix artifact for C5. Development/held-out design only; protect held-out answers from implementation chats. |
| C7 / D1 | Ready to assign; no executing owner identified. | Reserve a new `docs/delivery.md` for requirement mapping, demo/report outline and missing decisions. Shared README/launchers/locks remain unchanged during D1. |
| C3, C4, C6 | No executing owner identified. | C3 may inspect identity decisions read-only. Runtime and UI edits await the gates below. |

At the 0.1 inspection, other project chats found were idle or `notLoaded`; none was reported running on Fieldnote. Unassigned lanes above are ownership boundaries for future assignments, not claims that chats were created or briefed. No messages were sent to other chats.

## Shared contracts and integration order

Trace inspected: `RunRequest` -> `Application.load_company` -> `research.retrieve_company` -> original packet parsing -> `FinancialFact` / `Calculation` -> `Store.update` -> saved report/API; frozen/replay copy saved evidence and records.

The current C1 contract proposal is recorded here for checkpoint review:

| Boundary | Existing candidate behavior | Consumer rule / acceptance evidence |
|---|---|---|
| Evidence / original bytes | `source_kind` defaults to `legacy`; optional `packet` carries source documents, accession, issuer and dates. Downloads are scoped to hashes belonging to that run's evidence and served as attachments. | C6 must distinguish legacy, aggregate, original filing and synthetic evidence. Preserve hash verification, cutoff and download authorization tests. |
| Facts / calculations | Additive report lists default empty; Metric references optional fact/calculation IDs. Immutable content-derived IDs; `operating-margin-v1`, Decimal precision 28, HALF_EVEN, typed failures. | C4 references immutable inputs; do not mutate prior facts/calculations to implement correction. Confirm compatible issuer, concept, currency, duration, accession and scope before reuse. |
| Storage / legacy reads | New fact/calculation tables; save validates provenance/reproducibility; old report defaults remain readable. | Preserve accepted report bytes, historical provenance, idempotency, recovery, frozen and replay behavior. Passing new-record tests alone is insufficient. |
| Identity | `Ticker` and `UNIVERSE` still constrain reports and store validation to five issuers. | C3 must agree the identity representation with C0 before touching contracts, retrieval, store validation or API configuration. Directory membership is not financial coverage. |
| Budgets / partial results | Fresh company retrieval now reserves three source operations; the current tool limit remains 20. | C3's ten-company screen must account for multi-request retrieval and preserve partial results without silently increasing limits. Review reservation headroom at 0.2 before broadening the universe. |
| UI | TypeScript currently has no typed fact/calculation/packet representation. | A passing build does not prove U1 exists. C6 owns `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/styles.css`, interaction specs and `verification/design-contract.md`; shared API changes remain coordinated by C0. |

Integration sequence: verify the preserved C1 candidate and compatibility cases -> record 0.2 decision and any concrete follow-up -> create a committed feature checkpoint as a separate repository action -> base runtime worktrees on that exact checkpoint. Coordinate C3 identity and C4 claim/version proposals before either edits shared contracts. Integrate one shared-contract change at a time; C6 follows each agreed feature shape. Do not mistake a test rerun for independent gold review.

## Safe concurrency

| Work | Can proceed concurrently? | Isolation / boundary |
|---|---|---|
| C0 checkpoint review + C5 8.1 + C7 D1 | **Yes**, for independent work. | C5/C7 can use isolated worktrees from recorded commit `2c7f203`; restrict writes to their reserved new documents/artifacts. They must label C1 as pending and must not depend on its absent overlay. No worktrees or chats were started by this task. |
| C3 identity research | **Yes, read-only** now. | Produce an identity proposal for C0; no Ticker/UNIVERSE/API/store edits before 4.1 acceptance and identity agreement. |
| C6 U1 | **Preparation only** now; implementation after C1 contract acceptance and a feature-containing worktree. | One UI writer; record the report/API shape and legacy presentation cases first. |
| C3 runtime + C4 runtime | **Not yet**. | 4.1 gates C3; 4.2 gates C4. After acceptance use separate worktrees, coordinate shared-contract windows and cherry-pick/integrate sequentially. |
| Browser suites / migrations / live stores | **Serialize** unless explicit isolation is agreed. | Playwright fixes port 8000, one worker and `reuseExistingServer: false`. Each run needs a distinct data directory; do not stop another owner's server. |
| C8 / C9 / C10 | **Not selected**. | Wider discovery/events, forecasting and factor research remain extensions with their catalogue gates; they do not delay the core by default. |

Until a worktree is allocated, there is one writer in this checkout. Capacity, deadline, submission format, experiment allowance and inclusion of forecasting remain undecided; no calendar commitments or paid calls are implied.

## Completion and cleanup

C1 packet preparation and implementation are marked done in STATUS and the task catalogue. Independent review of 3.1 and C0 0.2 acceptance remain unchecked; no new development assignment is implied. [Remaining work in dependency order](workstreams.md#remaining-work-in-dependency-order) records every core and optional follow-on.

The [closeout record](../verification/integration/c1-closeout-20261031.json) records preservation and any removed regenerable C0 test data. The source packet, runtime evidence, recovery copies and prior check results are retained.

## Verification

See [C0 check record](../verification/integration/checks-20261031.json). Baseline proof checks the pre-existing file bytes and index entries again after coordination edits. Full backend regression uses isolated temporary stores and disabled live credentials; the source verifier runs offline. Production build checks the existing consumers compile. Browser interactions and a clean-environment restore are separate 0.2/release checks; none is claimed from this documentation checkpoint.
