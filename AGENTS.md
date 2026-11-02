# AGENTS.md

Rules for everyone who changes this repo: people, Claude Code, Codex and any other coding agent. Keep this file short.

- **The plan:** [PROJECT_GUIDE.md](PROJECT_GUIDE.md). Pick one unchecked task in §9 and do only that.
- **Sources, libraries, data providers:** [docs/REFERENCE.md](docs/REFERENCE.md).
- **History only:** `docs/archive/`. Read it if useful; never update it or follow it as a plan.

## Rules

1. **One task per branch.** Name the branch after the task. Small PRs. Never commit to `main` directly.
2. **Layout and dependency direction.** New code goes in the target layout (PROJECT_GUIDE §8): `finance` ← `data` ← `tools` ← `agents` ← `api`. `finance/` does no I/O. Tools never call an LLM. Agents never make HTTP calls; they use tools. The old pipeline (`application.py`, `research.py`, …) is baseline A: build beside it, don't rewrite it, and delete parts only when they block you.
3. **Adopt before you build.** Before writing a tool or adding a dependency, check the adopt-or-build table in REFERENCE §10. Licences don't matter (academic project). Pin exact versions (`==`) of anything new in `pyproject.toml`.
4. **No hidden caps.** No output-token caps, token quotas or cost budgets unless the user opts in. Retry 429/5xx with the SDK defaults. Never hard-code tickers, sectors or result counts. Never silently truncate input or output.
5. **Every tunable lives in `config.py`** with a comment saying why. Loop guards are generous (about 30–40 steps) and end in a partial result marked "stopped at limit", never an error.
6. **Flag, don't reject.** A small problem in an LLM answer becomes a flagged item, not a discarded answer.
7. **Missing configuration degrades, never crashes.** A data provider without its key is skipped and shown as "not configured". A fallback to another provider is always labelled with its `source`.
8. **Tests with every change; the network is always mocked** (see `tests/sec_fixture.py`). Keep files small: split a file rather than grow it past about 400 lines.
9. **Secrets:** never read, print or commit `.env`. A new setting goes in `.env.example` with its tier (0 = no key, 1 = free key, 2 = paid).
10. **No new docs.** No status files, summaries or plans. Tick the checkbox in PROJECT_GUIDE §9, and record decisions in PROJECT_GUIDE or REFERENCE.

## Commands (PowerShell, from the repo root)

| Task | Command |
|---|---|
| First setup and run | `.\start.ps1` |
| Install dev tools | `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` |
| Tests | `.\.venv\Scripts\python.exe -m pytest -q` |
| Lint | `.\.venv\Scripts\python.exe -m ruff check .` |
| Frontend typecheck + build | `npm.cmd --prefix frontend run build` |

CI runs the same checks on every push and PR. Red CI means no merge.
