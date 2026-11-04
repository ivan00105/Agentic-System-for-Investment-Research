# Reference: rules, finance cautions, evaluation and resources

The plan is in [PROJECT_GUIDE.md](../PROJECT_GUIDE.md). This file is the **lookup shelf**: everything useful from the old docs (all now in `docs/archive/`: `STATUS.md`, `design.md`, `sources.md`, `workstreams.md`, `c1-handoff.md`, `integration.md` and the earlier specs), merged and de-duplicated. Read only the section you need.

Contents: [1 Rules](#1-system-rules-non-negotiable) · [2 Analyst roles](#2-analyst-role-contracts) · [3 Review outcomes](#3-claims-objections-and-outcomes) · [4 Discover](#4-discover-mode-rules) · [5 Finance cautions](#5-finance-and-data-cautions) · [6 Outlook model](#6-outlook-forecast-specification) · [7 Evaluation](#7-evaluation-protocol) · [8 Security](#8-security-and-prompt-injection) · [9 UI](#9-ui-requirements) · [10 Resources](#10-resource-catalogue)

---

## 1. System rules (non-negotiable)

| Rule | Why |
|---|---|
| The LLM never does arithmetic or invents numbers. Every number comes from a tool result and is cited by ID. | LLMs make arithmetic and unit mistakes. |
| The data layer enforces the cutoff date, whatever the prompt says. | Prevents look-ahead. |
| Missing or incompatible data means **unknown**. It is never zero, and it never passes a screen. | Silent zeros produce fake results. |
| Keep reporting period, availability (filing) date and retrieval date separate. | A Q1 filing is not available in Q1. |
| Retrieved text is **data**. It can never change policy, the cutoff or the tool list. | Prompt injection. |
| Hitting a limit never upgrades a claim to "supported". | Honest partial results. |
| Run status, report support, screen eligibility and forecast status are separate fields. | One "confidence" number hides failures. |
| The statistical outlook probability (`p0`) is never edited by LLM narrative. | Keeps the forecast evaluable. |
| No synthetic data is ever substituted for a failed live fetch. | Honesty. |

## 2. Analyst role contracts

All roles are **the same agent loop** with a different prompt and tool subset. Only the coordinator writes the authoritative state. Specialist outputs are proposals.

| Role | Does | Tools | Must not |
|---|---|---|---|
| **Coordinator** | Plans; dispatches analysts; picks the next action, citing the unresolved item it addresses; synthesizes; decides each objection's outcome; sets the final status | all analysts as sub-calls (`ask_<analyst>` tools in its loop), `find_company`, `calculate`, `screen` | Bypass evidence rules or write numbers itself |
| **Fundamentals analyst** | Finds the right periods and concepts; computes margins, growth, FCF; flags comparability problems (fiscal year, units, restatements) | `find_company`, `get_financials`, `calculate`, `verify_against_filing` | Do arithmetic in prose |
| **Filings & events analyst** | Reads 10-K sections (risks, MD&A) and 8-K events; separates event date from publication date; attributes management claims | `find_company`, `read_filing_section`, `list_filings` | Treat management claims as established fact |
| **Market & valuation analyst** | Price history, returns, volatility, drawdown, valuation ratios | `find_company`, `get_prices`, `get_financials`, `calculate` | Present adjusted historical prices as tradable prices |
| **Outlook model** (not an LLM) | Statistical probability of beating SPY over the horizon | `get_outlook` | Be changed by narrative |
| **Critic** | Returns zero or more objections, each tied to a claim version, with an issue type and a requested check | read-only tools + `verify_against_filing` | Be bearish by default, edit evidence, or close an objection by agreeing |

The action trace saves short rationales, not chain-of-thought. A repeated action with no new inputs is skipped (action fingerprint).

Tool lists are enforced (`agents/roles.py`): the loop answers a call to any other tool with an "invalid" result. Decided in Phase 3: every tool the single agent (condition B) has belongs to some role in C, so B vs C isolates specialization rather than tool access. So every analyst can `find_company`, the market analyst also reads `get_financials` (market cap needs a share count, P/E needs earnings), fundamentals has `verify_against_filing` (the critic gets it too in Phase 4), and the coordinator can `calculate` across analysts' records. An analyst keeps its conversation, so the coordinator's follow-up builds on its earlier work; a follow-up lists the analyst's earlier findings by claim ID, so it can revise one as a new version. Decided in Phase 4: the critic's read-only tools are `find_company`, `get_financials`, `calculate`, `read_filing_section`, `list_filings` and `get_prices`, plus `verify_against_filing`; `screen` is left out, since reviewing one report never ranks companies.

## 3. Claims, objections and outcomes

- **Claim:** ID, **version**, statement, type (fact / calculation / interpretation), materiality (central / supporting / minor), cited fact, calculation or chunk IDs, status.
- **Objection issue types:** unsupported inference, contradictory evidence, wrong period/unit/entity, arithmetic error, stale source, misleading certainty, missing material risk.
- **Outcomes** (one taxonomy, used everywhere):
  - **defended**: evidence answers the objection, and the check is cited.
  - **corrected**: a new claim version is created, and dependent calculations and claims are recomputed.
  - **withdrawn**: the claim is removed, and dependent conclusions are reconsidered.
  - **unresolved**: the issue and its impact are shown.
- Each outcome must cite evidence or a calculation. A resolution on claim v1 does not validate v2. Track objections by ID, not by count.
- Each report section carries a status: **cited / qualified / abstained**. Qualify a single section rather than abstaining from the whole report. *Cited* only means every statement cites real tool records and the checker flagged nothing; whether the evidence really supports the statement is judged in evaluation (§7).
- Stop reviewing when no material objection has a feasible next action. More debate rounds can make results worse (Kaesberg et al. 2025).
- **How Phase 4 applies this** (`agents/critic.py`): "wrong period/unit/entity" is three issue types, so the evaluation can score each. An objection ID comes from its claim, version, issue and wording; the same issue on the same claim version again is a repeat and isn't routed (no new input, so no feasible next action). The **claim ledger decides** whether a claim changed, not the coordinator's word: a claim gone from the report is withdrawn (recorded in `ClaimLedger.withdrawn`), a new version is corrected only when the coordinator calls it corrected and cites evidence, and an unchanged claim can only be defended (with at least one cited record) or unresolved. One exception: a missing material risk is corrected by the claims the revision adds, since the claim it qualifies may rightly stay as it was. An answer that doesn't fit (defended with no citation, "corrected" with the claim unchanged, a changed claim without a cited "corrected", no answer) leaves the objection open with a note, and it goes back to the coordinator next round. The guard is `AGENT_CRITIC_ROUNDS` reviews (3), so at most 2 revisions; what the last review raises, and anything still open, ends unresolved with the reason. A material objection left unresolved, or a citation of a withdrawn claim, flags the claim, so its section is **qualified**; a claim that cites a claim with such an objection is flagged too (one step only, no full dependency graph). The coordinator is told who owns each claim (the analyst that wrote it, else one whose finding it cites, else itself); answering without asking that analyst is noted, not blocked.

## 4. Discover mode rules

1. Turn the question into a **ScreenSpec**: universe, filters (sector, revenue growth, margin, FCF > 0, valuation…), top-k, ranking rule. **Show it to the user.**
2. A vague term ("cheap", "safe", "best") gets a clarification question or an explicitly stated definition. Never silently invent one.
3. Each filter returns pass / fail / unknown. Unknown never passes. Ties break on a stable ID, never alphabetically by design.
4. Research the ranked candidates. If research finds a filter violation, exclude the candidate with its provenance and pull in the next one.
5. Show counts: screened, eligible, investigated, rejected, returned. Returning fewer than k is fine.
6. Every final pick must pass a deterministic acceptance test on validated facts.
7. Never imply the search covered "the whole market" unless the universe really was the whole market.
8. For a cheap first pass over many companies, the SEC **frames** API returns one concept for all filers in one call. Caveat: frames are calendar-aligned and return each company's **latest-filed** value (restated, not point-in-time), so verify shortlisted names with companyfacts. A company's value comes from the best tag it reports, but a larger total (`Revenues`, `SalesRevenueNet`, `RevenuesNetOfInterestExpense`) for the same period replaces ASC 606 contract revenue, which leaves out lease income and interest: UDR, a REIT, reported $11M of contract revenue against $1.7B in total, so its operating margin showed as 4,870%. A margin above 100% (`SCREEN_MAX_MARGIN`) or inputs whose fiscal years end more than a week apart (`SCREEN_PERIOD_SLACK_DAYS`) is flagged unknown with its reason. The value stays in the screen record, but it never passes a filter and is never ranked. BitMine's operating income, mostly crypto gains, was 73 times its revenue. On the CY2025 frames for every filer, this cut the operating margins above 100% from 31 to 11, and all 11 are flagged.
9. **Discover runs on current data only.** Frames aren't point-in-time, so a Discover with a past cutoff would already have used later information, and checking the shortlist afterwards can't undo that. For the same reason the `screen` tool answers "invalid" in any run with a past cutoff (a Check or Compare with `--cutoff`, the web page's cutoff, every evaluation case). Screen on fundamentals first, then check valuation (which needs prices) on the shortlist. Say for each metric which filers it covers (banks, IFRS filers, ADRs). Never describe the result as "the cheapest in the market".

**How Phase 5 applies this** (`agents/discover.py`, CLI `--universe`): a declared universe is a YAML file (name, source, date, companies with ticker and CIK); the bundled `sp500_tech` is today's S&P 500 Information Technology and Communication Services members from Wikipedia's constituents table (97 tickers, 94 companies), so it is survivorship-biased. A screener role (`prompts/screener.md`, no tools) writes the spec: `screen` filters, ranking, top-k, **price checks** (P/E, P/S, P/B, FCF yield, market cap, volatility, drawdown; these need prices, so they run per candidate, never in the screen) and every vague term with its definition and a question. An interactive terminal asks each question (Enter accepts the proposal), `--define TERM=MEANING` answers up front, and an unasked term is shown as "assumed: not confirmed by the user"; an answer goes back to the model, which revises the spec. `screen` ranks the whole universe; then the host walks the ranking: the **acceptance test** (`agents/acceptance.py`, rule 6) recomputes every filter on the latest 10-K (companyfacts, via `get_financials` and `calculate`) and every price check on the latest close, with no model, and each line cites its record; unknown fails. A candidate that passes gets a research run by condition B, C or D, with its own trace. A rejected candidate or a failed research run (one that failed, or ended with no claims in any section) is replaced by the next one; research runs are limited to top-k plus `DISCOVER_MAX_REPLACEMENTS` (3, `--replacements`), rejections cost no model call and don't count. Counts: screened, passed the screen, ranked, checked, rejected, researched, research failed, replaced, returned. The Discover trace holds the spec step, the host's tool calls (so the checks are frozen evidence) and one event per candidate; its `run_end.totals` add the research runs'. `--cutoff` is refused with `--universe` (rule 9).

**From the web page** (Phase 7), "Find companies" starts the same run. The universe is a bundled list (`GET /api/universes`) or the user's own tickers, checked against SEC's ticker list. The screener's draft spec and its questions are written to the trace (a `questions` event) and the run waits until the page sends the answers (an empty answer accepts the proposal); Cancel works while it waits. Its picks are researched by `WEB_DISCOVER_CONDITION` (B) unless Advanced options pick another.

**Answer choices** (5 Nov 2026): each vague term also carries 2-3 `options`, concrete readings the screen can apply (filters, price checks, rankings with thresholds), one marked recommended. The recommended one is always the term's `definition`, the reading the spec applies; if the model marks another or leaves the definition out, the schema fixes that rather than refusing the term. The page shows them as choices with the recommended one picked, plus Other with a text box; the terminal numbers them (Enter accepts the recommended one, a number picks one, text is your own definition). Picking the recommended one, or leaving Other empty, accepts the proposal as before; another option or text sets the term and goes back to the model. A term without options keeps the plain text box. Sector-relative readings ("below the sector median") aren't offered: the screen computes no sector statistics.

**Bigger lists** (5 Nov 2026). `sp500` is the whole S&P 500 from the same Wikipedia table (503 tickers, 500 companies, all 11 GICS sectors, as of 2026-11-05, tickers in SEC's style such as BRK-B). Like `sp500_tech` it holds today's members only, so it is survivorship-biased and the page says so; it is the default Find list and the one Help me start uses. `sec_all` is every SEC filer with a ticker, built from SEC's ticker list on the day (CLI `--universe sec_all`; the page shows it disabled, with the reason, when SEC access isn't configured). Measured on a cold cache from this machine: SEC's list held 8,004 companies (3,453 Nasdaq, 2,592 NYSE, 2,040 OTC, 22 Cboe, 9 TXSE, 138 with no exchange); a fundamentals screen (operating margin above 25%, revenue growth above 0) took 11 s and 9 frames requests (2.5 MB), 3 s warm; adding a SIC sector filter took 6-8 minutes and about 1,200 submissions requests (150-170 MB), one per company passing the other filters, cached for a day. Price checks still run only on the walked shortlist. That is reasonable next to a research run, so it is offered, with these caveats in its note and spec: about half the companies come back unknown (funds, foreign filers, shells, banks for margins); the screener's prompt gives the list's size and source instead of 8,000 names (`Universe.show_members`); and a margin's inputs can come from different revenue tags or fiscal years, so the screen aligns or flags them (rule 8) and the acceptance test rechecks each pick on the latest 10-K. A size filter such as revenue keeps out most shells.

## 5. Finance and data cautions

**SEC fundamentals**
- Select facts by concept + period (start/end) + form + filed date. **Never** "take the last value in the array", and never use the `fy` field as the period (it is the filing's fiscal year).
- Revenue appears under several tags (`RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`). Check all of them by recency. If values conflict for the same accession and period, abstain.
- ASC 606 contract revenue leaves out lease income (REITs) and interest (banks). So in companyfacts (`sec_facts.select`, behind Check, Compare and the acceptance test), as in frames (§4 rule 8), a larger `Revenues`, `SalesRevenueNet` or `RevenuesNetOfInterestExpense` in the same filing and period replaces it. The fact keeps its real tag, and a restatement only compares values under that tag, so a tag switch is not a restatement. The tax-inclusive contract tag never replaces the tax-exclusive one (Brown-Forman's sales include excise tax). UDR's latest 10-K reports $11.4M of contract revenue and $1,712M in total; before this, its operating margin showed as 4,870%.
- A margin above 100% (`SCREEN_MAX_MARGIN`) on the latest 10-K is unknown in Discover's acceptance test too, and the line still cites the record. With totals read, such a margin means income beyond revenue (BitMine's crypto gains) or revenue under a tag neither path reads, and passing "operating margin > 25%" on it would mean nothing. The screen and the acceptance test judge a filter the same way.
- Today's companyfacts holds later restated values. Filtering by cutoff does **not** recreate what investors saw then.
- Banks and insurers usually have no `OperatingIncomeLoss`. Foreign filers (20-F) use IFRS (`ifrs-full`), not `us-gaap`. Treat both as "unsupported" rather than failing silently.
- Fiscal years differ (AAPL ends in September, MSFT in June, NVDA in January), and some have 53 weeks. Label comparisons by period end. Consider TTM for cross-company comparison.
- Cash-flow statements are year-to-date. Q4 = annual − 9M only if definitions match. Never subtract balance-sheet values; never sum EPS.
- FCF = operating cash flow − capex is non-GAAP; watch the capex sign. Don't sum overlapping debt tags; say whether leases are included.
- A margin change is in **percentage points** (10% → 12% is +2 pp, not +20%).
- Zero or negative denominator → unavailable. Keep GAAP and non-GAAP labelled. A management statement proves the claim was made, not that it is true.
- A ticker is not a security, and a CIK is the filer. Map share classes (GOOG/GOOGL) so an issuer isn't counted twice.
- SEC fair access: a User-Agent with a real contact email, and under 10 requests/second.

**Prices and valuation**
- Choose the price adjustment (splits, dividends) explicitly and never double-adjust. Adjusted historical prices are not prices you could have traded at.
- Per-share numbers must use the same split basis as the price. Shares outstanding: `dei:EntityCommonStockSharesOutstanding` (cover-page date).
- Historical market cap = **as-traded (raw) close** × cover-page shares. yfinance's Close is already split-adjusted, so use it for current-price valuation only. Tiingo provides both raw and adjusted prices.
- 20 trading sessions ≠ 20 calendar days. Use an exchange calendar (holidays, DST).
- Survivorship: SEC ticker lists hold today's companies only. Never drop delisted losers or forward-fill their prices. Thirty current large caps make a case study, not a market result.

**Forecasts and backtests**
- An **LLM already knows what happened after a historical cutoff**. Date-filtering documents does not remove that knowledge, so LLM-based historical backtests are contaminated. Evaluate LLM judgement only **prospectively** (log now, score later), or on dates after the model's training cutoff.
- Overlapping 20-day labels are not independent. Split by date, purge immature labels, and keep an untouched test period.
- Every extra trial inflates the best result. Keep a trial log (see the PBO and Deflated Sharpe papers).
- Beating SPY is not the same as profit, and neither is the same as alpha. Brier score is not pure calibration. Compare models on the same cases.
- Macro data: use ALFRED vintages, not today's revised series.

**Other**
- A valid JSON schema, or two models agreeing, is not evidence a claim is supported.
- A timed-out API call may still be billed.

## 6. Outlook (forecast) specification

**Parked.** This is the original design, kept so it isn't lost. Revisit it when Phase 6 starts; don't build it before the core agent works.

| Item | Spec |
|---|---|
| Target | P(stock total return − SPY total return > 0) over **20 trading sessions** |
| Timing | Cutoff 17:00 New York on a trading day. Anchor = next session close. End = 20 sessions later. A prediction issued after the anchor is "missed". |
| Label | 1 if excess return > 0; ties = 0; unmeasurable = unresolved |
| Model | Pooled, regularized logistic regression on price features: 5/20/60-session returns, SPY-relative returns, 20-session volatility, distance from moving average, volume ratio. No ticker-ID features. |
| Baselines | 0.5 and the training-period base rate |
| Splits | By date across all stocks; expanding-window validation; purge labels that cross a split; calibrate on a separate earlier block |
| Scores | Brier (primary), log loss, reliability plot with bin counts, date-block bootstrap intervals |
| Records | Immutable `p0` + model, feature and data versions. An append-only prospective log, with outcomes added later. |

**Expectation:** short-horizon price direction is close to a coin flip, so matching the base rate is a normal result. Report it honestly.

## 7. Evaluation protocol

**Research question:** does an analyst team with a critic and revision loop give more correct, better-supported research than simpler set-ups, at acceptable cost?

| Condition | What it is | What it isolates |
|---|---|---|
| **A** | Deterministic pipeline + report template (the existing code) | What plain software already solves |
| **B** | Single agent, all tools, one self-review pass | Value of tools and the loop |
| **C** | Analyst team, no critic | Value of role specialization |
| **D** | Analyst team + critic + revision | The full system |

- **Isolated review test:** start from the **same saved draft and evidence**, then compare no revision, self-review and critic-guided revision. Use frozen evidence so that retrieval differences don't confound the result. CLI: `--review TRACE` runs D's critic and revisions on a saved run's final draft and records (`agents/isolated_review.py`); `--inject wrong_period` first swaps one key figure for an earlier fiscal year's fact from the same records while its words still name the later year, written to the trace as its own claim version by "injected". The draft and records are frozen, but the team's tools still run (mostly from the SEC disk cache). A price series fetched again can differ by float noise (Yahoo's adjusted closes), so its ID covers its rows and each version stays frozen under its own ID; `--recheck` recomputes a calculation from every version frozen under its inputs' IDs, for older traces that hold two under one (PROJECT_GUIDE Phase 3).
- **Cases:** a development set for tuning plus a separate held-out set that is never used for tuning. Mix of check, compare and discover questions, plus robustness cases: clean (the critic should change nothing), wrong period or unit, restatement, missing data, unknown ticker, impossible filter, API failure, injected instruction in filing text. Label injected defects separately.
- **Fair comparison:** A only covers what the old pipeline supports (five companies, annual figures), so compare A with the others only on those cases. B, C and D get the same cases, data and scoring. B's self-review and D's critic look for the same issue types (§3), not just checker flags. Decided in Phase 4: the self-review pass (`runner.py`, shared by B, C and D) always runs once, even on a draft the checker passes, and shows the lead the same issue list, claim view and evidence view as the critic (`agents/objections.py`); a second pass (`AGENT_SELF_REVIEW_PASSES` > 1) runs only while checker flags remain. So C keeps B's self-review and B vs C still isolates specialization, and D is C plus the critic. Compute isn't matched exactly, so report quality next to steps, tokens, cost and time rather than claiming a compute-matched baseline.
- **Gold labels:** written from SEC data by one person, without seeing system output. A second person checks a sample (at least 10 cases), and the report says how many were checked and how many were changed. Gold answers never appear in tool outputs.
- **Metrics:**
  - Numeric accuracy (value, period, unit) and citation validity (automatic)
  - Claim support, judged by humans on a sample (an LLM judge may triage only)
  - Coverage of required facts, so that omission can't win
  - Critic effect: wrong→right fixes, right→wrong damage, valid-objection precision
  - Risk coverage, justified abstention, and discover-mode correctness (filters satisfied, replacements correct)
  - Steps, tokens, cost, median and p95 latency, failure rate
- **Stats:** paired comparisons per case, bootstrap intervals, repeated runs on a subset to measure randomness. Label small samples "exploratory". Negative results are fine.
- **Freeze** the model ID and prompts before the held-out run, and upgrade nothing mid-ablation. Within one batch `eval/run_eval.py` enforces this: its `manifest.json` records the model, prompt and case-file hashes, the relevant `config.py` values and the git commit, and a resume with any of them changed is refused.
- **Component benchmarks (optional):** FinQA or TAT-QA for numeric reasoning, AgentDojo-style injection cases.

## 8. Security and prompt injection

- The host owns trusted context (run ID, cutoff, allowed evidence IDs). These never come from model arguments.
- Fixed tool registry. No eval, dynamic import, model-written SQL/Python/shell, broker tools or arbitrary URLs.
- Validate tool arguments (types, ranges, ticker exists, date ≤ cutoff). Cap payload sizes on **input** to tools; never truncate output silently.
- Sanitize retrieved HTML. API keys stay server-side; redact secrets in logs. The server listens on localhost only.
- Test case: an instruction hidden in filing text must not change the cutoff, widen tools or leak keys.

## 9. UI requirements

- Two entry points, **Check** and **Discover**, from one question box. Show the interpreted ScreenSpec or plan before or while running.
- Show a live **trace**: plan → analyst actions with one-line rationales → draft → objections → outcomes.
- Report: scope, company identity, cutoff, source dates; metrics with formula/input drill-down; facts vs interpretations vs counter-evidence; claim → objection → check → outcome history; outlook card labelled as a statistical model; limitations; separate statuses.
- Clickable citations open the source excerpt; focus returns when it closes.
- States: loading, empty, error, partial, success. Status is never shown by colour alone. Works at laptop and phone widths. Diagnostics go behind a disclosure.
- Export as Markdown or JSON. History lets you reopen saved runs; replay never calls a model.
- **Detail level** (decided 5 Nov 2026), a preference kept in the browser: the same engine and runs, shown three ways. **Beginner**: plain headings, a "Words used in this report" list that explains each finance term once, and the guided start. **Standard**: today's page. **Professional**: Advanced options open (agents, another model ID of the configured provider, and a Discover run that waits so the user can edit the spec as JSON, used as written with no model call), plus a raw figure table (every cited fact and calculation with its formula and inputs, unformatted) and CSV/JSON/Markdown exports. The other levels have the same options and table, folded away.
- **Help me start**, for a user with no company or criteria in mind: four multiple-choice questions (what matters most, time horizon, comfort with price swings, sector), each with a recommended answer and "Not sure", become a Find question over the biggest bundled list plus a preferences note, both editable. The note is added to the run's question inside `<preferences>` tags (`agents/preferences.py`), so the screener, the coordinator and every agent read it and the trace keeps it; History and the run page show it apart from the question. Dividends can't be screened yet, so that choice asks for strong free cash flow and says so.

## 10. Resource catalogue

Every resource from the earlier research, in one place. **When** column: **Now** = use in the current phases, **Later** = planned phase or extension, **Ref** = read or borrow ideas only, **Skip** = looked at and not worth it. **Licences are not a constraint**: this is an academic project, so use any library, code, idea or data source that helps, whether by calling it or by copying the logic. Credit sources in the report. Pin the version of anything you install.

### Adopt or build, tool by tool (survey of 2 Nov 2026)

How this was checked: the five awesome lists were read section by section, and every candidate's licence and latest release were taken from its PyPI, GitHub or docs page. Key claims were spot-checked by hand. **Nothing was installed or run**, so parsing quality is untested until Phase 1's fixture tests. Before building any tool, look here first. If you find something better, add a row.

| Need | Decision | How | Main risk |
|---|---|---|---|
| `find_company` | **Build** (~50 lines) | `company_tickers_exchange.json` for current tickers, plus SEC's [`cik-lookup-data.txt`](https://www.sec.gov/Archives/edgar/cik-lookup-data.txt) for historical and delisted names. Fuzzy match with `rapidfuzz`. | Name changes, delisted filers |
| `get_financials` | **Build** (extend our code) | Keep companyfacts plus our availability rule. Borrow edgartools' concept-fallback lists (bank revenue, `ifrs-full` concepts). Don't use its statement numbers: they default to the latest filing, so restated values appear silently. | Banks, IFRS and fiscal-year logic stay ours |
| `list_filings` | **Build** (thin) | Submissions JSON, including the older `files[]` pages. Take acceptance time from the JSON. | Paging; 8-K item codes |
| `read_filing_section` | **Adopt [edgartools](https://github.com/dgunning/edgartools)** (MIT, pin `==5.62.1`) as a parser only | We fetch and snapshot the bytes ourselves, then edgartools' `parse_html` splits them into Items (1A, 7, …). **Gate:** it must pass a hand-checked sample of ~10 filings, otherwise try [sec2md](https://github.com/lucasastorian/sec2md) or our own. | Odd layouts (combined Items, cross-reference indexes). v6.0 (due Nov 2026) changes missing-section behaviour. Adds ~22 dependencies (pandas, pyarrow, lxml). Returned text loses our byte offsets. **Gate passed 3 Nov 2026** on 12 filings (AAPL, MSFT, NVDA, AMZN, XOM, KO, JNJ, WMT, JPM, Citigroup's cross-reference index, TSM and BABA 20-Fs): Item 1A/3 boundaries right in 12/12, Item 7/5 starts right in 12/12, but the XOM and JPM MD&A runs into Item 8 (the tool flags an auditor's report inside Item 7). |
| `verify_against_filing` | **Build** on our `Document` parser | Our byte offsets are the provenance. Use [Arelle](https://github.com/Arelle/Arelle) (Apache-2.0) later as a test oracle. | iXBRL scale, sign and format transforms |
| `screen` | **Build** (one frames call) | Frames return the **latest-filed** value per company (restated, not point-in-time); say so in the UI. Bulk alternative later: [secfsdstools](https://github.com/HansjoergW/sec-fincancial-statement-data-set). | Restated values in screens |
| `get_prices` | **Build** one small adapter per provider. Order: [Tiingo](https://www.tiingo.com/documentation/end-of-day) if its key is set, then yfinance (no key), then Alpaca if keyed. See [Data providers by kind](#data-providers-by-kind-options-and-order). | Tiingo gives raw **and** adjusted OHLCV plus `divCash` and `splitFactor`. yfinance's Close is already split-adjusted (raw prices must be rebuilt from its split history). Cache each fetch in SQLite. | Tiingo free tier: 50 requests/hour, 1,000/day, 500 symbols/month. yfinance can break and rate-limits by IP. |
| `calculate`: valuation | **Build** `finance/valuation.py`, copying [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) formulas. That's simpler than calling the library, which needs pandas ≥ 3 and brings its own data source. | Add the guards it lacks: a zero or negative denominator returns "unavailable". FCF yield = FCF / market cap. Any DCF is an illustrative Gordon-growth model with g < r enforced. | Formula conventions differ between sources |
| `calculate`: risk | **Build** with the stdlib `statistics` module (~40 lines) | Use QuantStats or empyrical-reloaded as **dev-only test oracles**. Fix the conventions in code: 252 days, simple returns, rf = 3-month T-bill ([FRED DTB3 CSV](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3), no key). | DTB3 has blank days; handle them explicitly |
| Agent loop | **Build** (~150 lines) | Tool schemas come from Pydantic `model_json_schema()`. Use the SDK's default retries. At startup, check OpenRouter's `/api/v1/models` lists `tools` for the chosen model. | — |
| Retrieval | **SQLite FTS5** (built in; confirmed on Python 3.12 on Windows) | One row per Item chunk, with accession number and Item as columns for citations. Quote or OR the query terms, because raw text breaks FTS5 syntax. Fit check: model `context_length` against characters/4. | Add `sqlite-vec` only on measured misses |
| Report charts (web) | **Build** small SVG components (`frontend/src/components/agent/Charts.tsx`) | Revenue bars, a margin line and a price line (adjusted closes, so splits are no drop) per company, drawn from the run's frozen records; each chart's label lists its values for screen readers. Decided 4 Nov 2026: a library such as Recharts (about 100 KB gzipped) isn't worth it for 3-20 points. | Revisit if charts need tooltips, zoom or many series |
| Eval harness | **pytest + JSON** | LLM judge for triage only. [inspect_ai](https://pypi.org/project/inspect-ai/) later if needed. | — |
| Eval cases | **Draw from public sets** | ~15 from the FinanceBench open sample (re-derive gold from SEC data: FinanceBench uses as-filed PDFs, companyfacts holds restated values). ~8–10 from the Vals Finance Agent public set that are answerable from 10-K/XBRL. ~5 FinRetrieval-style fiscal-period traps. The rest hand-built: injection, bank, foreign filer, unknown ticker, restatement. | Some Vals questions need web search; take only those our tools can answer |
| MCP server (later) | **Adopt** the [`mcp` SDK](https://pypi.org/project/mcp/) v2 (MIT) | Pin the version: older tutorials use the v1 `FastMCP` API. | — |
| Outlook (parked) | scikit-learn + exchange_calendars + Ken French CSV, as an `outlook` extra | Hand-roll purge and embargo; use [purgedcv](https://pypi.org/project/purgedcv/) (MIT, young) as a cross-check. | — |

**Dependencies:** keep the core light, with no pandas or numpy before the Outlook. The exception is edgartools, which brings pandas and pyarrow. Accept that cost for section parsing, the hardest piece to hand-write.

**Supply chain:** pin every version. LiteLLM 1.82.7 and 1.82.8 on PyPI were credential stealers (24 Mar 2026, [incident note](https://docs.litellm.ai/blog/security-update-march-2026)).

### Data providers by kind (options and order)

Every kind of data has a few options, so nothing depends on one vendor. These rules apply to every kind:
1. **Tiers:**
   - **0** = free, no key
   - **1** = free with a key
   - **2** = paid

   Build tier 0 first, then tier 1. Write a paid adapter only when nothing free does the job, and leave it switched off until its key is in `.env`.
2. **Order:** each kind's provider list lives in `config.py`, in priority order. An env variable can override it, for example `PRICE_PROVIDERS=tiingo,yfinance`.
3. **Missing key means skipped, not an error.** The status page shows that provider as "not configured" and names the variable to set.
4. **Zero keys must work out of the box.** The only required settings are `SEC_USER_AGENT` (an email) and an LLM key. Adding a key upgrades that kind; removing one falls back.
5. **Fallback is allowed but never silent.** Every result carries `source`, and the trace records any provider that was skipped or failed.
6. **One series, one provider.** Don't mix providers inside one calculation, such as one price history. The evaluation pins the provider list so results are reproducible.
7. **No provider available** means the tool returns "unavailable: needs X", and the agent says so in the report.

**Status** (survey of 4 Nov 2026): **in use**; **next** = the shortlist for November 2026, ranked (1) to (7); **later**; **no**, with the reason. **Point-in-time** = usable at a past cutoff without later information. In tier 2, "cheap" means under about $20 a month. ✓ = checked on 4 Nov 2026 (official page or a live keyless call from this machine); other limits and prices come from secondary sources and are unverified.

| Kind | Status and why | Tier 0: free, no key | Tier 1: free with key | Tier 2: paid | Point-in-time | Default order |
|---|---|---|---|---|---|---|
| Fundamentals (XBRL) | **In use** | **SEC companyfacts** (only a User-Agent email; XBRL from 2009) | [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs) (250/day ✓), Alpha Vantage (25/day), [Finnhub](https://finnhub.io/docs/api) as-reported (60/min ✓), [SimFin](https://www.simfin.com/) (cross-checks only) | sec-api.io ($49); EODHD fundamentals (~$60); Arkleon (claims point-in-time SEC fundamentals, unverified); Compustat via WRDS | Partial: filed dates, but restated values mixed in (§5) | SEC |
| Filing text and sections | **In use** | **SEC Archives** + edgartools parser | — | sec-api.io extraction API | Yes (acceptance time) | SEC |
| Company identity | **In use** | **SEC** `company_tickers` + `cik-lookup-data`; FinanceDatabase | [OpenFIGI](https://www.openfigi.com/api) (a key raises limits; maps 13F CUSIPs to tickers) | — | Today's list only | SEC |
| Daily prices | **In use** | **yfinance** | **Tiingo** (50/hour, 1,000/day), Alpaca (200/min, from 2016), Alpha Vantage (25/day), [Twelve Data](https://twelvedata.com/), Massive (5/min, 2 years), EODHD (20 calls/day), FMP | Cheap: [EODHD](https://eodhd.com/pricing) All World (~$20, 30+ years, 60+ exchanges), [Market Data](https://www.marketdata.app/pricing/) ($12 billed yearly ✓). Paid: Massive ($29), Norgate or Sharadar (survivorship-free), CRSP via WRDS | Raw closes yes; adjusted closes change after splits | Tiingo if keyed → yfinance → Alpaca if keyed |
| Risk-free rate, macro, release dates | **Next (1)**: risk statistics have no risk-free rate yet (no FRED code exists); adds rate and inflation context and the releases inside a horizon | [Treasury daily bill rates CSV](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_bill_rates) (✓ works), FRED graph CSV (timed out from our network), [Treasury Fiscal Data](https://fiscaldata.treasury.gov/api-documentation/), [BLS](https://www.bls.gov/developers/) v1 (25 queries/day), [NY Fed rates](https://markets.newyorkfed.org/static/docs/markets-api.html) (SOFR), [Census](https://www.census.gov/data/developers/data-sets.html), [Econdb](https://www.econdb.com/api/) | **[FRED API](https://fred.stlouisfed.org/docs/api/fred/)** (✓ reachable; ALFRED vintages; `fred/releases/dates` gives the release calendar), BLS v2 (500/day), [BEA](https://apps.bea.gov/api/), [EIA](https://www.eia.gov/opendata/) | Trading Economics | **Yes with ALFRED vintages**; plain series are revised | FRED API if keyed → Treasury CSV |
| Earnings and events calendar | **Next (4)**: catalyst dates for days-to-weeks horizons; "what happened at the last results?" | **SEC 8-K** item codes (in use: 2.02 results, 5.02 officers, 1.01 agreements) | **Finnhub** earnings calendar (upcoming + 1 month back ✓) and IPO calendar; Alpha Vantage `EARNINGS_CALENDAR` | Finnhub paid (20 years), Wall Street Horizon | 8-K yes; future dates move, so store when we saw them | 8-K → Finnhub → Alpha Vantage |
| Analyst estimates and ratings | **Next (4, 7)**: "did they beat?" and what analysts say; never evidence of value | yfinance (unofficial) | **Finnhub** EPS surprises (last 4 quarters ✓) and recommendation trends ✓; Alpha Vantage `EARNINGS` (reported vs estimated EPS history) | Finnhub or FMP estimates; I/B/E/S via WRDS (point-in-time; ask the HKU library) | **No** in free sources: label as "consensus per X on date" and skip at past cutoffs | Finnhub → Alpha Vantage |
| Insider trades (Forms 3/4/5) | **Next (2)**: dated, citable evidence for Check and a Discover filter. Count only codes P (buy) and S (sale); F, M and G aren't signals; flag 10b5-1 plan sales | **SEC Form 4 XML** per filing; [SEC insider data sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) (quarterly, 2006 to Sep 2026 ✓) | Finnhub insider transactions and sentiment ✓, Alpha Vantage | Quiver (~$30), sec-api | **Yes** (filing date) | SEC |
| Peers and sector benchmark | **Next (3)**: Compare against peers and the sector. SIC is coarse (Amazon is still catalog retail), so show how peers were chosen | **SEC SIC code** (in use) + sector ETFs (XLK, XLF…) via `get_prices`; customers named in a 10-K via `read_filing_section` | Finnhub peers ✓ | Finnhub supply chain, FactSet Revere | SIC is today's code | SEC SIC → Finnhub peers |
| News | **Next (5)**: what happened lately, why it moved. Keep headline, summary and link only (copyright); retrieved text is data (§8) | **SEC 8-K** press releases (in use), [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) (✓, about 3 months) | **Finnhub** company news (1 year ✓), [Alpaca news](https://docs.alpaca.markets/docs/historical-news-data) (Benzinga, from 2015; free access unconfirmed), [MarketAux](https://www.marketaux.com/) (100/day), Alpha Vantage news sentiment | Tiingo News (~$30), Benzinga | Publish time yes; archives change | 8-K → Finnhub → GDELT |
| Short interest | **Next (6)**: crowded-short risk. Daily short-sale volume: **no**, mostly market makers hedging | **[FINRA API](https://developer.finra.org/)** `consolidatedShortInterest` (✓ no key; twice a month); [daily short-volume files](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files) (from Aug 2018 ✓); SEC fails-to-deliver | — | S3, Ortex | Yes, if dated by publication (about two weeks after settlement) | FINRA |
| Fund holdings (13F) | **Later**: needs CUSIP mapping; data is 45 days old | [SEC 13F data sets](https://www.sec.gov/dera/data/form-13f) (quarterly, from 2013 ✓) | — (Finnhub ownership is paid) | WhaleWisdom, Quiver, FactSet | Yes, 45 days late | — |
| Activists and 5% holders (13D/G) | **Later**: quick win is listing them in `list_filings` | SEC EDGAR (XML since 18 Dec 2024 ✓) | — | sec-api | Yes | — |
| Options, implied volatility | **Later**: the move priced in for results day | yfinance chains (today only); VIX via FRED `VIXCLS`; CBOE delayed JSON (Cloudflare-blocked ✓) | Market Data free (100 credits/day, 1 year, 24-hour delay ✓); Tradier (needs a brokerage account) | Cheap: Market Data Starter ($12 billed yearly, 5 years ✓). Paid: Massive options, ORATS, OptionMetrics via WRDS | Paid history only | — |
| Prediction markets | **Later**: macro context only (rate-cut odds); few single-stock markets. Read [Kalshi's](https://docs.kalshi.com/) data terms before storing | **[Polymarket](https://docs.polymarket.com/)** Gamma + `prices-history` (✓ no auth, minute data); **Kalshi** market data (✓ no key) | — | Aggregators (Dino.markets) | Yes (timestamped) | — |
| Commodities and FX | **Later**: nearly free once FRED is in | FRED (WTI, Brent, H.10 FX), [Frankfurter](https://frankfurter.dev/) (✓), [CFTC COT](https://publicreporting.cftc.gov/) (✓), yfinance futures | EIA, Alpha Vantage | Barchart | Yes | — |
| Fund and ETF flows, ETF holdings | **Later**: weak for a single stock | [ICI flows](https://www.ici.org/research/stats), SEC N-PORT (60-day lag), issuer holdings files | — (Finnhub ETF holdings are paid) | EPFR, FactSet | N-PORT yes | — |
| Government contracts, FDA and trials, patents | **Later**: each helps one sector | [USAspending](https://api.usaspending.gov/) (our network's TLS blocked it), [openFDA](https://open.fda.gov/apis/) (✓; 1,000/day), [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) (✓), Google Patents (BigQuery) | Finnhub USA spending, FDA meeting calendar and USPTO patents ✓; [USPTO Open Data Portal](https://data.uspto.gov/) (PatentsView moved there 20 Mar 2026 ✓; key needs a USPTO.gov account) | — | Mostly (records get edited) | — |
| Wikipedia pageviews | **Later**: attention context, weak signal | [Wikimedia pageviews](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/) (✓; daily from Jul 2015) | — | — | Yes | — |
| Non-US markets (e.g. HKEX) | **Later**: outside the US-listed scope. HKEXnews: **no**, its [terms](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use) ban scraping and text mining without written permission ✓ | yfinance (`0700.HK`); SEC 20-F/6-K (in use); [filings.xbrl.org](https://filings.xbrl.org/) (EU) | EDINET (Japan), DART (Korea), Companies House (UK) | Cheap: EODHD All World (~$20). Paid: EODHD fundamentals (~$60), HKEX licences | Varies | — |
| Other asset classes as context | **Later** via FRED; crypto **no** unless asked | Treasury/FRED yields, [CoinGecko](https://docs.coingecko.com/) (✓), CFTC, VIX | CoinGecko demo key (30/min) | FINRA TRACE bonds, CME | Yes | — |
| Factors | **Later** (Outlook, not wired) | **Ken French library** | — | — | Yes | Ken French |
| Other | **Later** | Credit-rating histories (SEC NRSRO XBRL), Federal Register, CourtListener (litigation, key) | — | Earnings-call transcripts (Finnhub, FMP) | — | — |
| Politicians' trades | **No**: up to 45 days late, amounts as ranges, studies find no reliable edge; the law bans commercial use (5 U.S.C. §13107) | House Clerk PTRs, Senate eFD | Veridion, CongressInvests (unvetted) | Quiver (~$30), Unusual Whales, Finnhub | 45-day lag | — |
| Social sentiment (Reddit, X, StockTwits) | **No**: closed or costly, bot-heavy, posts get deleted, not citable as fact | ApeWisdom Reddit counts (✓) | Reddit closed new API requests on 31 Oct 2026; StockTwits unclear | X pay-per-use (~$0.005 per post read) | No | — |
| Intraday bars, order flow, "unusual options activity" | **No**: microstructure noise at day-to-year horizons | yfinance 1-minute (~30 days) | Alpaca, Tiingo IEX, Massive | Databento, Massive | Yes | — |
| Google Trends | **No**: official API invite-only ✓; pytrends archived Apr 2025; each pull is resampled, so not reproducible | pytrends | Trends API alpha | SerpApi | No | — |
| Job postings, app and web traffic, ESG scores | **No**: paid and costly, no free history; ESG scores are vendor opinions | Company job boards, Tranco, App Store charts (today only) | Finnhub H-1B filings | LinkUp, Revelio, Similarweb, Sensor Tower, MSCI | No | — |
| LLM | **In use** | Local **Ollama** through `OPENAI_BASE_URL` (free; weaker tool calling; good for offline tests) | OpenRouter free models (rate-limited); HKU ITS quota (check) | **OpenRouter** pay-per-use (current), OpenAI | — | OpenRouter |

Terms to respect: Finnhub's free licence is personal use; Tiingo and EODHD data is for internal use; prefer the primary source over the many new wrappers on public-apis (one less dependency and citation hop). The next seven add about 11–13 days of work with AI help. A new tool changes conditions B–D, so land it before the held-out run is frozen, or keep it out of the evaluated tool set (web app only).

Sources read on 4 Nov 2026: [World Monitor](https://www.worldmonitor.app/docs/data-sources) ([repo](https://github.com/koala73/worldmonitor), AGPL-3.0; mostly geopolitics; its finance feeds are FRED, ECB, BIS, Treasury, EIA, CFTC, USAspending, CoinGecko and Polymarket), [public-apis](https://github.com/public-apis/public-apis) (Finance, Government, News, Social, Jobs, Patent, Health) and awesome-quant's data and prediction-market sections.

**Setup & status page (proposed, not built):** every row above lives in `data/providers.py` with its status, whether an adapter exists, env variable, free-tier limit, history, point-in-time flag and docs link, and a test checks each name appears in this table. Cards are grouped by question (company numbers, prices, events, insiders and ownership, news, macro and markets, alternative data). Built providers keep today's states and Test button; unbuilt ones show greyed as "planned" or "later" with the reason; "no" sources sit behind a disclosure. A summary line counts active, keyless-ready, needs-a-key and planned kinds.

### SEC filings and fundamentals
| Resource | Use for | When | Caveat |
|---|---|---|---|
| [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) (companyfacts, submissions, frames) | All fundamentals, filing lists, cross-company screens | **Now** | Free, no key. Frames are calendar-aligned and hold the latest-filed value, so they aren't point-in-time. |
| [SEC developer / fair-access rules](https://www.sec.gov/about/developer-resources) | User-Agent with email, <10 req/s | **Now** | Hard requirement |
| Examples: [MSFT companyfacts](https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json), [MSFT submissions](https://data.sec.gov/submissions/CIK0000789019.json), [EDGAR browse](https://www.sec.gov/edgar/browse/?CIK=789019&owner=exclude) | Test fixtures, manual checking | **Now** | |
| [SEC Inline XBRL](https://www.sec.gov/structureddata/osd-inline-xbrl.html), [XBRL specs](https://specifications.xbrl.org/) | Background for `verify_against_filing` | Ref | Don't build a full XBRL engine |
| [Form 8-K items](https://www.sec.gov/files/form8-k.pdf) | Event types for `list_filings` | **Now** (Phase 1) | |
| [Microsoft FY2024 annual report](https://www.microsoft.com/investor/reports/ar24/index.html) | Example of an issuer-side cross-check when writing gold labels | Ref | The company page is not the SEC record |
| [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | **Formula reference** for ratios (valuation, profitability, risk) | **Now** (as a reference) | Its FMP→Yahoo fallback silently changes the source; copy formulas, don't depend on it. No zero/negative-denominator guards; no FCF-yield function. |
| [edgartools](https://github.com/dgunning/edgartools) | 10-K/10-Q/20-F section parsing; concept-fallback lists | **Now** (parser only) | See the adopt-or-build table. Its default `get_financials()` returns the latest (possibly restated) values. |
| [sec2md](https://github.com/lucasastorian/sec2md) | Fallback section parser (page-aware Markdown, keeps tables) | Later | MIT, single maintainer, about a year old |
| [Arelle](https://github.com/Arelle/Arelle) | Test oracle for `verify_against_filing` | Later | Apache-2.0; a full XBRL processor, too heavy for runtime |
| [secfsdstools](https://github.com/HansjoergW/sec-fincancial-statement-data-set) | Bulk quarterly statement data for wider screens | Later | Apache-2.0; pins numpy<2 |
| [edgar-pit](https://github.com/broiisapro/edgar-pit), [pit-fundamentals-store](https://github.com/narasimhamungi/pit-fundamentals-store) | Point-in-time / restatement store designs | Ref | Weeks old; design ideas only |
| [sec-api](https://sec-api.io/pricing) | Spot-checking our section extraction with its 100 free calls | Ref | Paid service ($49/month) |

### Company identity and universe
| Resource | Use for | When | Caveat |
|---|---|---|---|
| [company_tickers.json](https://www.sec.gov/files/company_tickers.json), [with exchange](https://www.sec.gov/files/company_tickers_exchange.json) | `find_company`, discover universe | **Now** | Current companies only; save a dated copy |
| SIC code in the submissions JSON | Sector | **Now** | Coarse; map SIC → sector |
| [cik-lookup-data.txt](https://www.sec.gov/Archives/edgar/cik-lookup-data.txt) | All filer names, including historical and delisted | **Now** | ~13 MB; includes funds and individuals |
| [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) | Richer sector/industry metadata | Later | Stale-cache risk; metadata only |

### Prices and market data
| Resource | Use for | When | Caveat |
|---|---|---|---|
| [Tiingo EOD](https://www.tiingo.com/documentation/end-of-day) ([pricing](https://www.tiingo.com/about/pricing)) | `get_prices` first choice when keyed | **Now** | Free key; raw + adjusted, `divCash`, `splitFactor`; delisted coverage not documented |
| [yfinance](https://ranaroussi.github.io/yfinance/) | `get_prices` zero-key default | **Now** | Unofficial, can break; IP rate limits (cache); Close is already split-adjusted; pulls pandas/numpy |
| [Alpaca market data](https://docs.alpaca.markets/docs/about-market-data-api) | Second backup | Later | Free account key, 200 calls/min, history from 2016, explicit `adjustment=` parameter; terms not yet read |
| [Alpha Vantage](https://www.alphavantage.co/support/) ([adjusted daily](https://www.alphavantage.co/documentation/#dailyadj)) | — | Skip | 25 calls/day; adjusted prices are premium |
| [EODHD](https://eodhd.com/pricing) | — | Skip | Free tier 1 year / 20 calls/day |
| [Massive (Polygon)](https://massive.com/pricing) | — | Skip | Free tier 2 years, 5 calls/min, "adjusted" = splits only |
| Stooq CSV, [pandas-datareader](https://github.com/pydata/pandas-datareader), Nasdaq Data Link | — | Skip | Stooq needs an API key since March 2026; Nasdaq's free WIKI set has been frozen since 2018 |
| [Damodaran datasets](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html) | Equity risk premium, industry betas for an illustrative DCF | Later | Annual |
| [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars), [NYSE hours](https://www.nyse.com/markets/hours-calendars) | Trading-session maths for the outlook | Later (Outlook) | |
| [ML4T Data](https://github.com/ml4t/data) | Multi-feed download/storage helpers | Skip for now | No SEC; its Yahoo adapter returns adjusted prices without corporate actions |
| [FRED/ALFRED](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | Risk-free rate and macro context | Next (see [Data providers by kind](#data-providers-by-kind-options-and-order)) | Key needed; use vintages |
| [OpenBB](https://github.com/openbq-org/OpenBB) ([licence](https://github.com/openbq-org/OpenBB/blob/develop/LICENSE); [old repo](https://github.com/OpenBB-finance/OpenBB); [wind-down note](https://openbb.co/blog/openbb-belongs-to-everyone/); [OpenBQ](https://openbq.org/)) | One SDK over many data providers | Later, if we need 3+ providers | Apache-2.0; project stewardship changed |

### Quant, factors and forecasting
| Resource | Use for | When | Caveat |
|---|---|---|---|
| scikit-learn: [logistic regression](https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression), [calibration](https://scikit-learn.org/stable/modules/calibration.html), [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [Brier](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html) | Outlook model | Later (Outlook) | TimeSeriesSplit has `gap` but doesn't purge overlapping labels and isn't panel-aware. With under ~1,000 samples use sigmoid calibration. |
| [SciPy bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) | Confidence intervals in the evaluation | **Now** (Phase 8) | Resample by case, not by claim |
| Python [`statistics`](https://docs.python.org/3.12/library/statistics.html) | Volatility, beta (`linear_regression`), Sharpe, drawdown | **Now** | Stdlib, no pandas |
| [QuantStats](https://github.com/ranaroussi/quantstats), [empyrical-reloaded](https://github.com/stefan-jansen/empyrical-reloaded) | Dev-only test oracles for our risk stats | **Now** (tests only) | Too heavy at runtime (QuantStats pulls matplotlib, seaborn, scipy, pandas) |
| [TA-Lib](https://github.com/TA-Lib/ta-lib-python) | Technical indicators | Later, only if needed | Windows wheels now bundle the C library |
| [purgedcv](https://pypi.org/project/purgedcv/), [statsmodels](https://pypi.org/project/statsmodels/) | Purged/embargoed CV cross-check; OLS with HAC errors | Later (Outlook) | purgedcv: MIT, one author, first release May 2026 |
| [Fama–French data](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html) | Factor exposure, beta vs factors | Later | |
| [Qlib](https://github.com/microsoft/qlib), [ML4T Engineer](https://github.com/ml4t/engineer) | Feature engineering for outlook experiments | Later | Bring your own data |
| [vnpy](https://github.com/vnpy/vnpy), [QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | Factor-research references | Ref | Trading frameworks; out of scope |
| [quant-trading](https://github.com/je-suis-tm/quant-trading) | Educational strategy examples | Ref | Ignores fees and slippage |
| [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | Desktop terminal UI ideas | Ref | A desktop app, not a library |
| Lists: [awesome-quant](https://github.com/wilsonfreitas/awesome-quant), [awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading), [awesome-ai-in-finance](https://github.com/georgezouq/awesome-ai-in-finance), [Quant-Developers-Resources](https://github.com/cybergeekgyan/Quant-Developers-Resources), [Intro to Quant Finance](https://github.com/Barca0412/Introduction-to-Quantitative-Finance) ([arXiv list](https://barca0412.github.io/Introduction-to-Quantitative-Finance/arxiv/)) | Finding a tool when a concrete gap appears | Ref | [public-apis](https://github.com/public-apis/public-apis) (Finance and Government sections) is also useful, because its **Auth** column shows which APIs need no key. Many entries are new and unvetted, and some are dead (IEX Cloud closed in 2024). Mined on 2 Nov 2026 (results are in this section) and again on 4 Nov 2026 for every data kind ([Data providers by kind](#data-providers-by-kind-options-and-order)); go back when a new gap appears. Being listed doesn't mean quality. |

### Other people's agent designs (what we borrow)
| Project | Borrow | Don't borrow |
|---|---|---|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) ([paper](https://arxiv.org/abs/2412.20138)), Apache-2.0 | Analyst-team structure (fundamental / news / technical analysts); **bull vs bear case** in the report; Pydantic structured outputs for manager roles; EDGAR statements "as filed"; a decision log with later reflection (useful for memory later); a possible external baseline | The trader agent, execution and multi-round debates (cost; more rounds can hurt); social-sentiment feeds |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) V2, Apache-2.0 | Confirms our design: a lead agent over pipeline agents plus bull, bear and judge agents, and "numbers are code-calculated" (our `{calc:ID}`) | V0 (AutoGen, educational); it makes no evaluation claims |
| [Dexter](https://github.com/virattt/dexter) (TypeScript) | Append-only log per query; soft per-tool call limits that **warn rather than block**; near-duplicate query check (word overlap ≥ 0.7); eval set as a CSV of question + rubric with an LLM rubric judge and a `--quick` sample | Its prompt has no citation or anti-fabrication rule; ours must. It's TypeScript, so port ideas rather than code. |
| [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund), MIT | Each analyst returns a stance (−1…+1) plus a short thesis, and code (not the LLM) aggregates | Persona prompts, position sizing, trading |
| [QuantMind](https://github.com/LLMQuant/quant-mind) ([roadmap](https://github.com/LLMQuant/quant-mind#-roadmap)) | Typed, provenance-carrying extraction records | Its SEC collection was still unbuilt |
| [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | Bounded tools, grounding, explicit missing-value handling | The full trading platform |
| [QuantDinger](https://github.com/OpenByteInc/QuantDinger) | Workflow and UI layout ideas | Trading and distributed services |

### LLM and agent APIs
| Resource | Use for | When |
|---|---|---|
| [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Python SDK](https://github.com/openai/openai-python) | Agent loop (works with OpenRouter and other compatible APIs) | **Now** |
| [OpenAI model selection](https://developers.openai.com/api/docs/guides/model-selection), [latest model](https://developers.openai.com/api/docs/guides/latest-model) | Choosing models | Ref |
| [OpenRouter Responses](https://openrouter.ai/docs/api_reference/responses/overview), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) | Current provider; check the model supports tools | **Now** |
| [HKU ITS GenAI quota](https://its.hku.hk/services/ai-as-a-service/hku-chatgpt/) | Possibly free eval runs | Check |
| SQLite FTS5 (`bm25()` ranking) | Filing-section search | **Now** |
| [pydantic-ai](https://pypi.org/project/pydantic-ai/) (MIT) | The only agent framework worth a look (has an OpenRouter provider); FinRobot V2 uses it | Later, only if our loop becomes painful |
| [sqlite-vec](https://github.com/asg017/sqlite-vec) (MIT/Apache-2.0) | Embeddings, if FTS5 measurably misses passages | Later (pre-v1; Windows wheel exists) |
| [`mcp` SDK](https://pypi.org/project/mcp/) (MIT) | Expose our tools as an MCP server | Later (pin v2) |

### Evaluation datasets and papers
| Resource | Use for | When |
|---|---|---|
| [FinanceBench](https://huggingface.co/datasets/PatronusAI/financebench) open sample (150 questions, CC BY-NC 4.0) | Filing-grounded questions with evidence and justification → ~15 eval cases | **Now** (Phase 8) |
| [Vals Finance Agent](https://github.com/vals-ai/finance-agent) public set (50 questions with rubrics) | Question types and rubrics; the questions answerable from 10-K/XBRL | **Now** (Phase 8) |
| [FinRetrieval](https://arxiv.org/abs/2603.04403) (CC BY 4.0) | Fiscal-year naming and period traps for agents (it reports a 5.6 pp loss from them) | **Now** (Phase 8, borrow case styles) |
| [Multi-agent document-processing benchmark](https://arxiv.org/abs/2603.22651) | Prior art for our A–D comparison: on SEC extraction a reflexive loop scored F1 0.943 at 2.3× cost vs a sequential baseline, a hierarchical one 0.921 at 1.4× | Report |
| [DocFinQA](https://huggingface.co/datasets/kensho/DocFinQA) | Whole-section vs FTS5 retrieval test (long-document QA) | Later |
| [FinQA](https://github.com/czyssrs/FinQA) ([paper](https://aclanthology.org/2021.emnlp-main.300/)) | Optional numeric-reasoning component test | Later |
| [TAT-QA](https://github.com/NExTplusplus/TAT-QA) | Optional table+text reasoning test | Later (check contamination) |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | Template for prompt-injection test cases | **Now** (Phase 8) |
| [Du et al. 2024, multi-agent debate](https://proceedings.mlr.press/v235/du24e.html) | Motivation for critic/review | Report |
| [Kaesberg et al. 2025](https://aclanthology.org/2025.findings-acl.606/) | Evidence that more rounds can hurt → stop early | Report |
| [Backtest overfitting (PBO)](https://arxiv.org/abs/1407.0340), [Deflated Sharpe](https://ssrn.com/abstract=2460551) | Outlook / any strategy claims | Later |

### Engineering references
| Resource | Use for |
|---|---|
| [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Codex worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees), [Codex models](https://learn.chatgpt.com/docs/models), [git worktree](https://git-scm.com/docs/git-worktree) | Team and AI-tool workflow (Phase 0) |
| [SQLite transactions](https://www.sqlite.org/lang_transaction.html), [Python Decimal](https://docs.python.org/3/library/decimal.html), [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/) | Store and calculations |
| [React](https://react.dev/learn), [Playwright assertions](https://playwright.dev/docs/test-assertions), [Playwright a11y](https://playwright.dev/docs/accessibility-testing), [WAI-ARIA APG](https://www.w3.org/WAI/ARIA/apg/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | UI and browser tests |
| [Backlog.md](https://github.com/MrLesk/Backlog.md) ([config](https://github.com/MrLesk/Backlog.md/blob/main/ADVANCED-CONFIG.md)), [Groma](https://github.com/MrLesk/groma.md) ([agent instructions](https://github.com/MrLesk/groma.md/blob/main/docs/agent-instructions/backlog.md), [Python scanner](https://github.com/MrLesk/groma.md/blob/main/docs/scanners/python/index.md)) | The dev-panel idea from `tasks/plan.md`. **Skip**: GitHub Issues + the guide's checkboxes are enough. |

### Looked at and skipped (2 Nov 2026)
So nobody re-researches these. Reconsider one only if its reason stops being true.

| Area | Skipped | Why |
|---|---|---|
| Agent libraries | LiteLLM, instructor, OpenAI Agents SDK, smolagents, LangGraph | OpenRouter already unifies models. Our loop is small, and it is the part being graded. smolagents executes model-written code. The Agents SDK uploads traces by default. LiteLLM had the March 2026 PyPI compromise. |
| Retrieval | bm25s, rank_bm25, tiktoken | FTS5 already does BM25. tiktoken only knows OpenAI vocabularies; use the API's `usage` instead. |
| Eval / tracing | promptfoo, DeepEval, Ragas, Langfuse, Arize Phoenix | Our checks are deterministic, and the SQLite trace is enough |
| Eval datasets | FinBen/PIXIU, FinSearchComp | Mostly NLP tasks or web search, not filing QA |
| Finance LLMs | FinGPT, FinMem, FinCon | Fine-tuned sentiment or trading memory; no tool use |
| SEC parsing | sec-parser, sec-parsers (unmaintained); doc2dict (generic); datamule (vendor-shaped); sec-edgar-downloader, secedgar (download only); sec-edgar-api (stale since 2023); py-xbrl (a full engine; Arelle covers it); python-xbrl (dead); finagg (old pins) | edgartools plus our own code cover the need. [edgar-crawler](https://github.com/nlpaueb/edgar-crawler) is a script, not a library, but its Item regexes are a usable fallback. |
| SEC MCP servers | sec-edgar-mcp, edgartools' bundled MCP | Our agents call tools in-process |
| Prices | defeatbeta-api | Yahoo mirror; stale; adjustment not documented |
| Quant libraries | numpy-financial (1.1.0 needs Python 3.13), ffn, fincore, pandas-ta (unclear maintenance), skfolio, mlfinlab (paid), mlfinpy, timeseriescv, arch, getfactormodels (pre-alpha) | Heavy, dead, paid or off-target; a few lines of our own (or purgedcv) do the job |

Origin of the whole plan: [original ChatGPT planning conversation](https://chatgpt.com/share/6ad4955b-b618-83ea-afcc-303b0e8e8767).
