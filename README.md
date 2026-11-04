# Fieldnote

An agentic AI research assistant for US stocks. You can **check** a stock or **discover** stocks that match what you want, and every number in the report is traced to its source.

**Status:** the data, storage and UI layers work. The agent team (coordinator, analysts, critic) is being built. Live retrieval currently covers Microsoft, Apple, Amazon, Alphabet and NVIDIA. The bundled saved reports use **invented figures** for demonstration.

| Read                                   | For                                                                    |
| -------------------------------------- | ---------------------------------------------------------------------- |
| [PROJECT_GUIDE.md](PROJECT_GUIDE.md)   | What we're building, where we are and what to do next. **Start here.** |
| [AGENTS.md](AGENTS.md)                 | Rules for people and AI coding tools working on the repo               |
| [docs/REFERENCE.md](docs/REFERENCE.md) | Rules, finance cautions, evaluation, data providers and libraries      |
| `docs/archive/`                        | Old plans and records (history only)                                   |

## Run

Requires Python 3.12+ and Node 22.12+. In PowerShell, from this folder:

```powershell
.\start.ps1
```

Then open http://127.0.0.1:8000. The first run needs internet to install dependencies. Keep the terminal open; press Ctrl+C to stop. The server only accepts local connections.

To ask the research agent one question in the terminal (it prints the report and where the step-by-step trace is saved; `--cutoff YYYY-MM-DD` researches as of an earlier date; `--condition C` uses the analyst team instead of the single agent):

```powershell
.\.venv\Scripts\python.exe -m research_assistant.cli "Compare Apple and Microsoft: growth, margins, valuation."
```

The trace keeps every tool result in full, so a saved run's numbers can be rechecked offline: `--recheck data\traces\<run>.jsonl`.

If PowerShell blocks `start.ps1`, run the steps by hand:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m research_assistant.cli
```

## Configure

Copy `.env.example` to `.env` and fill in what you need. `.env` is git-ignored: never commit or share it. Restart the server after changing it.

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad .env
```

| Variable                                | Purpose                                                                     |
| --------------------------------------- | --------------------------------------------------------------------------- |
| `SEC_USER_AGENT`                        | App name and your real contact email, required by SEC for financial data    |
| `RESEARCH_MODEL_PROVIDER`               | `openrouter`, `openai` (default) or `compatible`                            |
| `RESEARCH_MODEL`                        | Model ID (currently must support the Responses API with structured outputs) |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | Key for the chosen provider                                                 |
| `OPENAI_BASE_URL`                       | Endpoint for a `compatible` provider (for example a local Ollama)           |
| `RESEARCH_DATA_DIR`                     | Optional: a different folder for the database and saved sources             |

The **Connections** page shows what is configured and has a test button for each connection.

## Develop

| Task                                                      | Command                                                  |
| --------------------------------------------------------- | -------------------------------------------------------- |
| Backend tests                                             | `.\.venv\Scripts\python.exe -m pytest -q`                |
| Lint                                                      | `.\.venv\Scripts\python.exe -m ruff check .`             |
| Frontend typecheck + build                                | `npm.cmd --prefix frontend run build`                    |
| Browser tests (stop the server first; they use port 8000) | `npm.cmd --prefix frontend test`                         |
| Frontend dev server (with the Python server running)      | `npm.cmd --prefix frontend run dev`, then open port 5173 |

Tests never use your `.env` and never call real services. To back up, copy the whole `data/` folder while the server is stopped.
