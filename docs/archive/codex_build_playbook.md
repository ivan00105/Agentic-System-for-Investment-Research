> Archived on 27 October 2026. Historical design/review context; it may describe unimplemented behavior. For current guidance use [Start](../../README.md), [Status](../../STATUS.md), [Design](../design.md) and [Sources](../sources.md).

# Codex build playbook and model choices

Prepared 19 October; execution order updated 26 October 2026. Companion to the [technical blueprint](./technical_blueprint.md) and [implementation plan](./implementation_plan.md).

Implementation update: [Fieldnote](../../README.md) now contains the custom React/TypeScript/Vite workspace, thin FastAPI boundary and local foundation. Use STATUS.md as the authoritative implementation status and remaining work order; the research stages in this playbook remain future work where explicitly identified. Preserve its labelled synthetic/live distinction and do not describe the full research specification as delivered.

## 1. Separate development agents from application agents

Codex is the development assistant: it edits files, runs tests, inspects failures and reviews changes. The application agents are Python-controlled model calls that inspect financial evidence during a user's research request. Their prompts, tools, state and evaluation belong in the application repository.

Changing the model in the Codex composer does not change the application's runtime model. Similarly, adding a critic to the application does not require a permanent critic chat in Codex. A coding subagent's context is not the research application's memory.

Use the saved documents and current code as the design/integration reference. Implement one milestone at a time. A fresh implementation chat can point at the saved documents and current code; it does not need the entire brainstorming conversation. Keep a short `STATUS.md` with the last working command, completed milestone, known failure and next acceptance criterion. Do not treat chat memory as the source of truth for requirements.

## 2. Recommended Codex model and effort

These are task-specific recommendations, not measured performance results on this project. They are consistent with current official guidance describing Sol as a balanced choice, Luna for focused repeatable work, and Astra for the hardest work. Availability depends on the account/client. [Official model selection](https://developers.openai.com/api/docs/guides/model-selection).

| Development task | Starting model | Effort | Why |
|---|---|---|---|
| Ordinary feature implementation with clear acceptance tests | GPT-6.1 Sol | Medium | Default balance for repeated coding and integration |
| Initial contracts and ownership decisions | GPT-6.1 Sol | High | Errors here spread across modules |
| Simple UI copy, documentation, small isolated edits | GPT-6 Luna | Low or Medium | Well-bounded work with easy verification |
| SEC fact selection, restatements, units/period semantics | GPT-6.1 Sol | High | Several interacting correctness conditions |
| Forecast labels, time splits and leakage investigation | GPT-6 Astra | High; Extra High for unresolved subtle cases | Concentrate stronger reasoning on high-impact scientific errors |
| Broad architecture decision or hard failure spanning modules | GPT-6 Astra | High or Extra High | Use when the ambiguity is real and local attempts are insufficient |
| Routine review of a completed feature | GPT-6.1 Sol | High | Check behavior and tests from a fresh perspective |
| Milestone review of data/evaluation integrity | GPT-6 Astra | High | Independent attempt to find counterexamples |
| Repeated mechanical changes after one pattern is established | GPT-6 Luna | Medium | Low ambiguity; inspect a representative diff and run checks |

Use **Sol / Medium as the everyday setting**. Escalate based on a concrete failure or difficult invariant. Do not run every task at Max or Ultra. Extra effort cannot repair absent evidence or a wrong target definition; fix the inputs first. Model × effort × number of agents all affect consumption.

In the desktop app, use the composer model/effort controls or Advanced controls where available. Current documentation identifies Ultra as involving subagents, rather than simply a larger single-agent reasoning budget. Use it only for genuinely separable work with clear boundaries. It is not an API `reasoning.effort` value to copy into your application. [Codex/desktop model documentation](https://learn.chatgpt.com/docs/models).

For the direct OpenAI API, GPT-6.1 Sol documents `low`, `medium`, `high`, `xhigh` and `max`; `none` and `minimal` are unsupported. Use Responses for its tool calls. Product UI labels and API values need not match exactly. [GPT-6 model guide](https://developers.openai.com/api/docs/guides/latest-model).

If Sol is unavailable through your university endpoint, use a model that actually passes its tool/structured-output capability test, and freeze that model across the first experiment. There is no evidence here that the HKU gateway exposes every publicly documented model or reasoning setting.

## 3. Models inside the financial application

Start with **GPT-6.1 Sol / Medium for every LLM role**, if accessible. Keep arithmetic, screening, regression, probability scoring and calendar logic in ordinary code. This makes the initial comparison about workflow design.

After the full workflow is evaluated, test this cheaper deployment candidate:

| Application role | Candidate configuration | Required evidence before adopting |
|---|---|---|
| Coordinator | Sol / Medium | Appropriate follow-up and stopping decisions |
| Filing/event extraction | Luna / Medium | Comparable extraction and citation support on held-out cases |
| Quantitative explanation | Sol / Low or Medium | No altered tool numbers or invented causal explanation |
| Critic | Sol / High | More valid corrections without more harmful revisions |
| Difficult unresolved case | Optional Astra / High | A predefined escalation trigger and measurable gain per extra cost |
| Numerical calculations and forecasting model | No LLM | Deterministic tests and chronological evaluation |

Do not silently escalate only the full system during an ablation. Either keep role settings identical across comparable conditions or label heterogeneous-model deployment as a separate experiment. If a stronger critic helps, that does not by itself show that adversarial organization was the cause.

On a small development set, compare success rate, review-induced damage, calls/tokens/cost and latency. Keep the least expensive configuration that meets the agreed quality bar. Freeze models/effort/prompts before the held-out run. Record actual API model identifiers and snapshot identifiers where supported; a moving alias is a reproducibility limitation.

Use a dedicated application API/gateway credential and budget. Do not assume that access to a model in Codex establishes entitlement, quota or billing for an independent application. Keep Codex development usage and application experiment usage as separate budget items.

## 4. How to organize coding work

Initially use one implementation chat plus a separate review pass. Do not start five agents implementing five roles independently: they would each make incompatible assumptions about facts, state and finalization.

After the contracts and first working path are committed, parallelize only independent tasks. A useful split is data/metrics, forecast/evaluation utilities, and UI over the agreed report contract. Keep one integration owner. Shared files such as contracts, workflow, lockfile and schema need coordinated ownership.

For parallel editing chats, use separate Git worktrees or branches. Worktrees provide independent checkouts but do not merge semantic differences for you; integrate one reviewed change at a time. They require a Git repository. [Official worktree documentation](https://learn.chatgpt.com/docs/environments/git-worktrees).

Subagents within an implementation task are useful for bounded reading, independent review or a genuinely isolated change. Ask explicitly for them when needed. Do not assume subagents have separate filesystems; assign non-overlapping edits or keep reviewers read-only. Do not create additional user-visible chats unless you want to manage them yourself.

Example delegation request for later:

> Use one read-only subagent to inspect forecast label leakage and another to inspect evidence cutoff enforcement. Give each the current implementation and invariants. They should report concrete counterexamples and file locations. Keep edits with the main agent, reconcile findings, and implement only verified fixes with focused tests.

This is a suggested review prompt, not an instruction to create extra chats or duplicate shared-file ownership.

## 5. Repository instructions to establish

The application repository already exists. If adopting a project-root `AGENTS.md`, keep it limited to stable rules. Codex reads these instructions according to directory scope; the official [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md) explains discovery and precedence. Keep task status in `STATUS.md`, rather than continually expanding the instruction file.

Suggested project rules:

```text
Build the stock research application described in docs/.
Keep course materials and unrelated files unchanged.

The host owns cutoffs, provenance, tool authorization and budgets.
LLMs propose actions and claims; they cannot override those rules.
Financial arithmetic uses validated facts and named Python functions.
Missing/ambiguous data is explicit; never replace it with invented values.
Forecast probabilities and source snapshots are immutable records.
Training labels must be observable before each fitting cutoff.
Never weaken a correctness test to make an implementation pass.
Keep secrets outside code, fixtures and logs.
Use focused fixture tests; paid/network tests are opt-in and labelled.
Document new run commands only after executing them successfully.
For a completed milestone, report changes, proof and material limitations.
```

Add the actual setup/test commands when they exist. Do not copy unimplemented commands into `AGENTS.md` and then report they passed. Avoid a generic library of elaborate agent policies; the project's domain invariants are the useful instructions.

## 6. Build stages and ready-to-use Codex tasks

These stages follow the current order in [STATUS.md](../../STATUS.md). The original initialization-first sequence is superseded.

### Existing baseline — preserve, do not recreate

The project directory, Git repository, environment, local web UI, saved-run lifecycle, synthetic examples and narrow SEC/model integration already exist. Use the commands in the README and inspect current tests before extending them. The synthetic correction is a teaching example, not a live correction workflow.

### Stage 1 — eligible evidence and typed calculations

Use High effort for source/contract decisions and ordinary effort for mechanical integration.

> Extend the existing annual SEC path. Archive an accession-specific original filing/table packet, retain availability and source locators, and carry issuer, concept, unit, period and scope into the calculation boundary. Compare reviewed revenue tags by recency; reject incompatible or ambiguous inputs. Add focused restatement, cutoff, period/unit and missing-data cases. Preserve old saved-report replay. Demonstrate one independently hand-checked annual packet; mock fixtures alone do not prove live access.

The application already has Responses integration. Configure the actual endpoint/model through the existing environment settings, then run one explicitly budgeted capability test when credentials are available. Keep fixture checks runnable beforehand. Do not create a provider framework or guess account entitlement.

### Stage 2 — bounded follow-up and real corrections

Use High effort for claim-state and numerical invariants.

> Extend the current worker and interpretation/critic path. Add immutable fact/calculation references, claim versions, version-targeted objections, dispositions and resolution evidence. Allow only bounded source checks and named calculations. Demonstrate error correction, a clean claim retained, an invalid objection rejected and unresolved issues surviving exhaustion. Recompute dependent results after a corrected input. Preserve a tool-using single-agent condition and a role-only condition for comparison; do not add services merely to represent roles.

Narrative support needs independent assessment; two agreeing model calls do not prove a source supports a claim. Keep review at two rounds maximum within the existing shared run budgets.

### Stage 3 — corrected discovery and report integration

> Reuse the research path in Discovery. Re-screen corrected inputs and replace an ineligible selected candidate within the existing universe and shared budget. Preserve pass/fail/unknown and allow fewer results than requested. Retain explicit alphabetical selection until validated forecast ranking exists. Present results, sources, dates, corrections and limitations first; keep diagnostics behind disclosure. Preserve refresh-safe URLs and idempotent retry behavior.

Do not add natural-language filters or expand the universe as part of this integration.

### Stage 4 — frozen research evaluation

Use a separate methodology review after the runner works.

> Freeze cases, source packets, prompts, model settings and budgets before held-out evaluation. Compare deterministic, tool-using single-agent, role-only and critic-enabled conditions. Isolate review using the same initial drafts/evidence and include self-review. Measure factual/numerical correctness, coverage, harmful revisions, failures, latency and actual usage. Keep semantic human assessment separate from automated ID/number checks. Report negative findings and affected reruns without selectively rerunning poor outcomes.

Mocked outputs verify runner behavior. Research-quality claims require actual evaluated outputs and independently checked references. Size the paid run using measured pilot usage and the team's declared budget.

### Stage 5 — separate forecasting baseline, later

> Validate one daily-price source and explicit corporate-action/calendar conventions. Implement the target and base-rate/logistic baselines in the implementation plan. Split all securities by date, exclude labels not matured at fitting time, and fit transformations only on training data. Add holiday, split/dividend, overlapping-label and future-row-invariance checks. Record every model/feature trial and reserve the final test. Keep LLM narratives from changing probabilities.

Freeze the precise forecast target before experiments. GP, neural-network and LLM factor mining are later optional research, not prerequisites for the report/correction system. Portfolio/trading simulations remain outside this milestone.

## 7. A useful review prompt

Use this after a coherent milestone, with a fresh review context when practical:

> Review this milestone against the specification and invariants. Trace the actual code paths. Focus on factual/temporal correctness, numerical semantics, silent fallbacks, error states, evaluation leakage and whether tests exercise those boundaries. Give concrete findings with triggering examples and file locations. Do not propose speculative features or rewrite code merely for style. Do not edit during this review. If there are no findings, say what was checked and what remains untested.

Then ask the implementation chat to assess and fix confirmed findings. A fresh reviewer reduces anchoring on the author's explanation, but it does not guarantee independence of model errors.

## 8. Your responsibilities and immediate next action

You should make the product/research decisions, verify a small set of financial ground truths, approve the evaluation protocol before seeing results, protect API budgets and ensure the group understands what it will demonstrate. Codex should handle implementation, tests, tracing, documentation and investigation of concrete failures.

The custom-web milestone now has a runnable local foundation. Next, use Sol / High to verify one real annual evidence packet and the team's runtime API access, then proceed with the next research acceptance criterion. Use the installed frontend-design-direction skill for UI changes and browser-testing-with-devtools for rendered verification; preserve screenshots and the checkable design contract. Before paid experiments, establish actual gateway access and quota. The existing Git repository and custom web foundation are the integration baseline; assign non-overlapping files or isolated worktrees for parallel edits.

Completion of one stage should yield a working command and a specific proof, not only scaffolding or a promise that the pieces will connect later.
