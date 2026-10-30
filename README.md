# Fieldnote

A local workspace for researching companies, inspecting sources and revisiting saved reports. Live retrieval currently supports Microsoft, Apple, Amazon, Alphabet and NVIDIA; the bundled saved examples for those companies use synthetic data.

**The bundled demonstration uses invented financial figures.** Its Microsoft 3% → 15% correction is a saved teaching example. Live correction and forecasting are still being developed.

## Start

Requires Python 3.12+ and Node 22.12+. From this project directory in PowerShell:

```powershell
.\start.ps1
```

Open [Fieldnote](http://127.0.0.1:8000). First setup needs internet; saved examples need no API credentials afterward. Keep the terminal running; press Ctrl+C to stop. The server is local-only.

## Where to look

| You want to… | Read |
|---|---|
| See what works and what comes next | [Current status](STATUS.md) |
| Assign a focused task to a separate work chat | [Work chats and task catalogue](docs/workstreams.md) — owners, dependencies, finish lines and starter prompt |
| Understand the architecture, contracts or evaluation | [Design](docs/design.md) — diagrams first, detailed references expandable |
| Choose sources/tools or understand factor research | [Sources](docs/sources.md) |

## Try the example

1. Open the Microsoft saved report. Under **Inputs & source**, inspect annual revenue and operating income.
2. Select **Evidence 1**, then follow the recorded correction. **Source details** contains the locator and hash.
3. Open Discovery: missing data stays **unknown**. Use History to reopen a report; refresh does not start a new run.
4. Open **Connections** to see setup status and the latest provider attempt during this server session. Opening or refreshing it makes no provider calls. Explicit test buttons start a saved connection-check run.

In **History**, add or change a report name and archive/restore reports. Archived reports stay readable through saved links and keep their source evidence. Organizing a report does not edit its financial results or run new research; clear its name to return to the default label.

| Action | What happens |
|---|---|
| Open saved report | Reopens an existing result; no retrieval or model call |
| Review saved sources again | Uses the original sources/cutoff; model analysis is optional |
| Research with latest available sources | Retrieves annual SEC facts eligible before your cutoff and calculates the figures; model analysis is optional |

**Include model analysis** starts unchecked. Financial figures work without model credentials; fresh research still needs SEC access. Reports show financial availability and model-analysis status separately. An unavailable or failed model review keeps the financial results usable. Synthetic data is never substituted for failed live retrieval.

## Setup and development

<details>
<summary>Enable SEC retrieval and optional model analysis</summary>

To configure live access, copy the example once in PowerShell, then edit your local file:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad .env
```

Uncomment and fill in only the settings you need. Save as UTF-8 (with or without a byte-order mark). Fieldnote loads `.env` from the project folder when the server starts; restart after changing it. Existing environment variables take precedence, including empty values. Values are literal; `${...}` expansion is not supported. Connections displays setup and runs explicit checks but does not write settings or store credentials.

| Variable | Purpose |
|---|---|
| `SEC_USER_AGENT` | Application name and real contact email for SEC requests |
| `RESEARCH_MODEL_PROVIDER` | `openai` (default), `openrouter`, or `compatible` |
| `OPENAI_API_KEY` | OpenAI or trusted compatible-provider credential; Codex access does not supply it |
| `OPENROUTER_API_KEY` | OpenRouter credential when its provider is explicitly selected |
| `RESEARCH_MODEL` | Accessible model supporting Responses structured outputs |
| `RESEARCH_DATA_DIR` | Optional alternative database/snapshot directory |
| `OPENAI_BASE_URL` | Optional trusted compatible endpoint; compatibility must be tested |

`SEC_USER_AGENT` is sufficient for financial retrieval. Add model credentials only to enable model analysis, then select it explicitly in the research controls.

For OpenRouter, set `RESEARCH_MODEL_PROVIDER=openrouter`, `OPENROUTER_API_KEY` and an explicit `RESEARCH_MODEL`. Remove `OPENAI_BASE_URL`: OpenRouter uses the fixed `https://openrouter.ai/api/v1/responses` endpoint. Automatic model routing and online-search model variants are rejected. Requests disable storage, SDK retries and provider fallbacks, and require parameter support. OpenAI and trusted compatible endpoints remain available; compatible access uses `OPENAI_API_KEY` and `OPENAI_BASE_URL`.

`.env` is ignored by Git; keep it private and do not commit or share credentials. Before a live experiment, check account/model capability and agree a small budget. Mocked input/output tests do not establish model quality or real provider access.

Connections separates **Configured** from **Not tested / Check passed / Check failed**. **Test SEC connection** retrieves MSFT facts without a model call. **Test model connection** uses selected saved evidence for at most one interpretation and one critic call; it requires a positive USD allowance and consent to send evidence and incur charges, including confirmation that a provider/key spending cap is set. The app cannot guarantee that allowance as a dollar cap. An uncertain submission can be recovered with the same submission key.

Results describe provider attempts in this server session, not source correctness; restarting clears them. Opening saved examples and replay do not count as checks. Saved reports retain per-call model, response ID, tokens and provider-reported cost; missing cost is **unknown**, never zero. The latest live SEC/model check outcomes and their limits are recorded in [STATUS](STATUS.md).

</details>

<details>
<summary>Manual installation if PowerShell blocks start.ps1</summary>

These commands avoid changing machine policy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m research_assistant.cli
```

</details>

<details>
<summary>Development, checks and backup</summary>

| Task | Command |
|---|---|
| Backend tests | `.\.venv\Scripts\python.exe -m pytest -q` |
| Production UI build | `npm.cmd --prefix frontend run build` |
| Browser checks | `npm.cmd --prefix frontend test` |
| Frontend dev server | `npm.cmd --prefix frontend run dev` |

Stop the normal server before browser checks: tests use port 8000 and a separate test database. Backend and browser tests disable local `.env` loading and isolate provider settings; `.env` tests use temporary files. Browser checks use installed Chrome and save screenshots in `verification/` unless `FIELDNOTE_VERIFICATION_DIR` overrides the destination.

For UI development, run the Python server and frontend dev server in separate terminals; open port 5173. Vite proxies `/api` to port 8000. Production uses one Python server for UI and API. Only one server may own a data directory.

Back up the **entire `data/` directory while the server is stopped**; it contains the database and saved source bytes. There is no destructive cleanup/reset endpoint. See [Design](docs/design.md#rules-that-must-survive-changes) for runtime, API and retry behavior, and the [UI verification contract](verification/design-contract.md) for interaction checks.

</details>

<details>
<summary>Earlier plans and review history</summary>

These are archived references, not the current work order:

- [Original research specification](docs/archive/implementation_plan.md)
- [Detailed target interfaces](docs/archive/technical_blueprint.md)
- [Source/methodology audit](docs/archive/source_audit.md)
- [October alignment review](docs/archive/alignment_review_2026-10-25.md)
- [Earlier coding playbook](docs/archive/codex_build_playbook.md)

Update the existing document that owns the topic instead of adding a new summary after each change. The task catalogue owns detailed chat assignments; historical decisions remain available here and routine changes belong in Git.

</details>
