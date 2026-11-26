# Fieldnote: evidence-linked stock research

You ask a question in plain English. The agent plans the work, calls tools, writes a cited report and checks it. The program fills number slots from saved tool results and flags unsupported figures. The report supports stock research.

## 1. What you need

- Windows with PowerShell. Python 3.12 or newer. Node 22.12 or newer. Internet. No GPU or special hardware.
- A contact email for live SEC EDGAR requests (free, no key). With SEC access unconfigured, eligible cached SEC data can still be used.
- One model key for live research. We used OpenRouter (paid per use) with `deepseek/deepseek-v4.1-flash`. You can open the app and browse saved runs without the key.

As a guide to cost, a short question averaged about $0.02 with the single agent, $0.03 with the analyst team and $0.09 with the team with critic in our four-case comparison. One broad company report with the critic cost $0.53 and took 34 minutes. Charges depend on the question, provider and cache.

## 2. Set up and run

```powershell
.\start.ps1
```

It creates `.venv`, installs Python and frontend dependencies, builds the page, and serves http://127.0.0.1:8000. Press Ctrl+C to stop. The server is for one trusted local user. It accepts local connections and has no account login. Live research sends prompts and relevant tool evidence to the selected model service.

If `start.ps1` is blocked, run these one at a time:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

```powershell
npm.cmd --prefix frontend ci --no-audit --no-fund
```

```powershell
npm.cmd --prefix frontend run build
```

```powershell
.\.venv\Scripts\python.exe -m research_assistant.cli
```

### Configure

Copy `.env.example` to `.env` and fill in what you need. Never commit or submit `.env`. Restart after a change. The Setup & status page shows what is configured.

| Setting                                                                        | Needed                                           | Tier        |
| ------------------------------------------------------------------------------ | ------------------------------------------------ | ----------- |
| `SEC_USER_AGENT` (app name and a real contact email)                           | For live SEC access                              | 0, free     |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (or OpenAI, or a compatible endpoint) | One of them                                      | 2, paid     |
| `RESEARCH_MODEL_PROVIDER`, `RESEARCH_MODEL`                                    | Optional, picks the default                      | –           |
| `TIINGO_API_KEY`                                                               | Optional, raw prices                             | 1, free key |
| `FRED_API_KEY`                                                                 | Optional, macro vintages and more exchange rates | 1, free key |
| `FINNHUB_API_KEY`                                                              | Optional, event calendars                        | 1, free key |
| `RESEARCH_DATA_DIR`                                                            | Optional, another data folder                    | –           |

Without the optional keys the app uses yfinance, Treasury and Frankfurter, and shows the source.

## 3. Use the app

Open **Research** and enter a question about one or more companies. Pick the discovery option to screen a list of companies against your criteria. Expand **Advanced options** to choose a research configuration or set a cutoff for a named-company question. Open **History** to revisit a saved report and its evidence.

| Kind                                     | Input                                                                                                                                                | What to expect                                                                                                                     |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Ordinary                                 | `What were Apple's revenue and operating margin in its latest fiscal year, and how did they change from the year before?`                            | Cited figures with fiscal year-end dates. If a figure cannot be found, the report says so.                                         |
| Changed request: add a historical cutoff | `What was NVIDIA's revenue in fiscal 2024, what are its main risks, and what is the outlook for the stock?` Set `--condition B --cutoff 2024-03-31`. | Fiscal 2024 revenue from filings available by the cutoff. The cutoff limits retrieved data; the model may still know later events. |
| Failure: unknown ticker                  | `How did QZXV's revenue change over its last two fiscal years?` Set `--condition B --cutoff 2026-11-03`.                                             | No figure is given, because no SEC company matches. The report may list similar names.                                             |

Command line:

```powershell
.\.venv\Scripts\python.exe -m research_assistant.cli "Compare Apple and Microsoft: growth, margins, valuation."
```

`--condition` selects the setup: `B` single agent (CLI default), `C` analyst team, `D` team with critic. Add `--cutoff YYYY-MM-DD` for a historical date. The web app defaults to the team with critic for Check and Compare and the single agent for each Discover pick. To run Discover through the CLI, use `--universe sp500_tech`, with `--define TERM=MEANING` and `--replacements N` if needed. Discover uses current data and refuses `--cutoff`.

Recheck a saved run offline, with no network and no model:

```powershell
.\.venv\Scripts\python.exe -m research_assistant.cli --recheck "path\to\your-saved-run.jsonl"
```

Replay recomputes saved calculations. It cannot yet recompute base rates (how often similar companies did something) and lists any it skips.

To run the critic on your own saved draft with a planted wrong-year citation, use the command below. It calls the model and can incur charges.

```powershell
.\.venv\Scripts\python.exe -m research_assistant.cli --review "path\to\your-saved-run.jsonl" --inject wrong_period
```

## 4. Evaluate

The evaluation uses the same letters: B single agent, C analyst team, D team with critic. A is a fixed pipeline without a model, kept as a control.

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py --conditions B --split dev --out data\eval\my-batch
```

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py --rescore data\eval\my-batch
```

- Useful options: `--cases ID,ID`, `--repeats N`.
- B, C and D call the model and cost money. Rescore is offline.
- A resume is refused if the model, prompts, settings, cases or code changed.
- Use `--split dev`. The report gives no held-out results.
- Saved results: `data/eval/<batch>/scores.md`. Traces: `data/traces/` and `data/eval/<batch>/traces/`.

## 5. Model settings

| Setting                    | Value                                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------------------------------- |
| Model                      | `deepseek/deepseek-v4.1-flash` via OpenRouter, host "Wafer" skipped because of unusually long replies |
| API interface              | OpenAI-compatible Chat Completions tool calling                                                       |
| Temperature, top-p, seed   | Unset (host defaults)                                                                                 |
| Step guard                 | 30 per tool loop. The initial draft and self-review share this allowance.                             |
| Self-review                | 1                                                                                                     |
| Critic reviews             | up to 3                                                                                               |
| Retries                    | 6 per model call, 2 for a broken reply                                                                |
| Resent tool-argument guard | 20,000 characters max resent on later turns (full payload stays in trace)                             |
| Output-token cap           | none                                                                                                  |

All in `src/research_assistant/config.py`.

## 6. Versions

Python 3.12+ and Node 22.12+. Checked with Python 3.12.10 and Node 22.20.0. `requirements.lock` pins FastAPI 0.146.0, httpx 0.28.1, NumPy 2.5.4, OpenAI SDK 2.54.0, pandas 3.1.0, Pydantic 2.14.1, Uvicorn 0.54.0, RapidFuzz 3.14.6, edgartools 5.62.1, exchange_calendars 4.13.2, yfinance 1.7.0, PyYAML 6.0.3 and pytest 9.1.1. `pyproject.toml` pins the development linter, Ruff 0.17.1. `frontend/package-lock.json` pins React 19.3.1, Vite 7.3.7, TypeScript 5.9.3, Playwright 1.64.1 and @axe-core/playwright 4.14.0.

## 7. Checks

| Task                                  | Command                                      |
| ------------------------------------- | -------------------------------------------- |
| Tests (network mocked)                | `.\.venv\Scripts\python.exe -m pytest -q`    |
| Lint                                  | `.\.venv\Scripts\python.exe -m ruff check .` |
| Frontend build                        | `npm.cmd --prefix frontend run build`        |
| Browser tests (stop the server first) | `npm.cmd --prefix frontend test`             |

## 8. What is mocked or missing

- Backend tests use stand-ins for providers and the model. Browser tests use the installed Chrome channel and start their own local server from the built frontend.
- The bundled teaching examples use invented figures.
- Not evaluated: held-out cases under a frozen protocol, quality of Discover picks, and live forecast outcomes. Reference answers have not been independently checked by a person. The direction forecast showed no skill in our offline check, and two known bugs in the finance code remain (report Section 5.4).
- The scripts in `data/report/offline_checks/` are a record of the offline checks. They need a code snapshot and price file that are not included, so they do not run from this package.
- The report's Appendix lists where each piece of evidence is stored.
