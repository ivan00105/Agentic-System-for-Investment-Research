# Sources and factor decisions

[Start](../README.md) · [Current status](../STATUS.md) · [Design](design.md)

**Enough references exist for the next milestone.** Prioritize validated evidence and evaluation. The 25 October reviews were README-level. The 27 October follow-up checked official provider access pages plus selected manifests, licences and relevant code for ML4T, Qlib, TA-Lib, Fincept and FinanceDatabase. Neither review was a full audit or reproduced performance test.

## What to use, and when

These are references and candidates, not installed application integrations.

| Resource | Decision for Fieldnote |
|---|---|
| [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | Formula reference or selected checked calculations. Enforce one source; provider fallbacks must not silently change provenance. |
| [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) | Possible later symbol/universe metadata seed. Validate identities; it is not a price/fundamental feed or historical membership record. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Workflow ideas and optional external baseline. Pin revision, eligible evidence and budgets; control cross-run memory. |
| [QuantMind](https://github.com/LLMQuant/quant-mind) | Typed provenance/extraction ideas. Its inspected README still placed SEC/filing collection on the roadmap. |
| [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | Selected bounded-tool, grounding and missing-value patterns. Its full trading platform exceeds this project's current needs. |
| [QuantStats](https://github.com/ranaroussi/quantstats) | Later analytics for a defined return series. Does not evaluate citation correctness, probability calibration or execution validity. |
| [vnpy](https://github.com/vnpy/vnpy) | Later `vnpy.alpha` feature/model research reference; no execution-framework adoption now. |
| [QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | Later factor-testing concepts; broad ecosystem support does not prove data suitability for these US issuers. |
| [QuantDinger](https://github.com/OpenByteInc/QuantDinger) | Selected workflow/UI ideas. Trading and distributed services would expand scope substantially. |
| [quant-trading](https://github.com/je-suis-tm/quant-trading) | Educational strategy examples. Its frictionless assumptions omit fees, slippage and illiquidity. |
| [awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | Lookup index for later baselines and original research. Listed results do not transfer to this application. |
| [awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | Find a tool only when a concrete gap appears; listing does not validate quality or data rights. |
| [awesome-ai-in-finance](https://github.com/georgezouq/awesome-ai-in-finance) | Find original papers/tools; inclusion is not evidence of accuracy or investing skill. |
| [ML4T Data](https://github.com/ml4t/data) | Reconsider acquisition/storage helpers when several feeds justify their dependencies. The inspected provider table has no direct SEC acquisition; its Yahoo adapter requests adjusted prices without actions. |
| [ML4T Engineer](https://github.com/ml4t/engineer), [Qlib](https://github.com/microsoft/qlib) | Later feature engineering and forecasting experiments. Neither grants data access; check released-version examples and dataset availability before use. |
| [TA-Lib Python](https://github.com/TA-Lib/ta-lib-python) | Later technical indicators from supplied prices; no market-data feed. Add only for an actual indicator requirement. |
| [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | Separate desktop workstation; skip embedding. README/commercial-licence guidance and LICENSE contain conflicting licensing statements; clarify before copying code. |

Before adopting code, pin a version, inspect its licence and test the exact functions used. A package licence does not grant provider subscriptions or rights to redistribute cached data.

### OpenBB and OpenBQ

**No migration is needed:** Fieldnote has no OpenBB dependency. Keep direct SEC retrieval; reconsider an integration platform when several actual providers justify it.

The [OpenBB announcement](https://openbb.co/blog/openbb-belongs-to-everyone/) describes the business wind-down and OpenBQ stewardship. [OpenBQ](https://openbq.org/) describes an independent foundation backed by BrightQuery. The inspected [platform licence](https://github.com/openbq-org/OpenBB/blob/develop/LICENSE) is Apache 2.0. Workspace/FINOS plans, hosted services and the data-platform repository are distinct; the OpenBQ site marked Workspace/Agents source releases as in progress at review time. Recheck the chosen release and endpoints before any integration.

## Factors

A feature is an input or candidate signal. **Beta** measures exposure to a market or factor. **Alpha** is performance unexplained by a specified risk model; beating SPY alone does not establish it. Trading writing also uses “alpha” informally for a candidate signal. [Fama–French definitions](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html) distinguish constructed factor returns from company-level ratios.

| Family | Useful role | When |
|---|---|---|
| Fundamental | Explain financial results and screen companies. Valuation also needs aligned prices, share counts and accounting dates. | Annual revenue/income/margin now |
| Technical | Fixed return, volatility and volume features for a statistical baseline | After historical prices are validated |
| GP / neural networks | Search candidate transformations or predictive relationships; GP means genetic programming here | Separate later experiments |
| LLM-derived | Extract cited, dated attributes/events or propose hypotheses; deterministic code computes values | Validate extraction first; predictive testing later |

Before mining, require chronological splits, matured labels, training-only transformations/selection, a trial registry, baseline comparisons and an untouched test. Report uncertainty and failed hypotheses. Five teaching companies cannot establish broad cross-sectional alpha. Strategy-return claims also need positions, costs, turnover and execution assumptions. See the [forecast protocol](design.md#how-to-evaluate-research).

## Data choices

SEC company-facts retrieval currently supports MSFT, AAPL, AMZN, GOOGL and NVDA. Those same companies also have labelled synthetic fixtures; the five-company restriction is the implemented live universe, not merely the demo selection. Optional model analysis supports OpenAI, OpenRouter and trusted compatible endpoints separately. Configure each data type when its integration exists; do not add unused keys or a universal data-provider selector. Free software does not grant data subscriptions or rights to save/share datasets.

Access and advertised prices checked **27 October 2026**; documentation updated **29 October 2026**. Live SEC retrieval and an OpenRouter interpretation/critic pair passed; an earlier model answer was rejected. Broader data quality, account eligibility and demonstration rights remain unverified. No data subscription is required for the current milestone; optional model calls may incur charges.

| Need | Initial choice / alternatives | Cost or acceptance boundary |
|---|---|---|
| Filings / accounting | Direct [SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces); original filing/table retrieval follows | Public access without an API key; contact identity required. Validate accession, dates, units and original table. |
| Company directory | Searchable SEC US directory planned after original filing evidence and typed validation; FinanceDatabase later for broader metadata | Current universe is five mappings. Directory identity/search is not financial evidence or ranking. Save the selected list/date; current metadata is not historical membership. |
| Optional model review | OpenAI, [OpenRouter](https://openrouter.ai/docs/api_reference/responses/overview), or a trusted compatible endpoint | Server `.env` or environment configuration and explicit model choice; model check needs saved evidence, consent, a positive allowance and provider/key spending-cap confirmation. App limits cannot guarantee a dollar cap; missing reported cost remains unknown. An OpenRouter interpretation/critic pair passed with the current configuration; see STATUS for the recorded run. |
| Historical prices | Evaluate [Massive](https://massive.com/pricing) when price research begins | Free individual tier advertises two years of end-of-day history and five calls/minute. Validate splits/dividends and usage rights. |
| Longer price history | Compare [EODHD](https://eodhd.com/pricing) and educational access | Free: one year, 20 calls/day. EOD plan: US$19.99/month; student discount advertised. Data quality and rights still require checking. |
| Financial/price alternative | [Alpha Vantage](https://www.alphavantage.co/support/) | Standard free: 25 calls/day; verified educational projects may receive more. [Daily adjusted prices](https://www.alphavantage.co/documentation/#dailyadj) require premium access; extra quota does not prove endpoint entitlement. |
| Personal price prototype | [yfinance](https://ranaroussi.github.io/yfinance/) | Free software, unofficial access and personal-use data limitations. Not a guaranteed service or redistribution licence. |
| Macro, later | [FRED/ALFRED](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | API key required; retain historical vintages rather than using today's revised values in past decisions. |
| Events / news, later | Eligible SEC 8-Ks/exhibits and issuer material first; general news deferred | Save source text and publication time; confirm content rights before adding a news service. |

No authenticated price/news entitlement or free-tier budget was established. No silent provider switch is permitted. Evaluate required coverage, adjustments, storage/replay and sharing rights before price. FinanceDatabase's inspected cache refreshes daily and can return older cached data on download failure: preserve a dated snapshot if adopted. A company announcement supports attribution to management, not the truth of a future outcome; syndicated stories are not independent confirmation.

The next data milestones are one independently checked original annual filing packet, typed fact/calculation validation, broader company search, then a real financial screen over up to ten user-selected companies. Wider automatic candidate sourcing comes later. These steps do not require installing every listed integration; add price history or news when a defined research task needs it.

## Resource packs for work chats

Use these packs with the [task catalogue](workstreams.md). Read the required items for the assigned task; the repository/tool catalogue above is optional lookup. **New links in these packs are starting references, not a fresh web audit:** this planning pass checked local code/docs, not current remote contents, prices or account entitlements. Earlier review dates/limits above still apply. No new dependency, subscription or connection has been installed or validated by listing it here.

For each adopted data/tool source, record URL and version/access date, intended task, licence and data rights, required account/cost, saved sample location, tested capability and fallback. Mark it **reference only**, **sample checked**, **integrated**, **blocked** or **deferred**. A fallback may be an explicit unavailable result; provider substitution must preserve the user's declared source choice.

### R0 Project and integration

| Read / inspect | Use and required output |
|---|---|
| [STATUS](../STATUS.md), [Design invariants](design.md#rules-that-must-survive-changes), [work assignments](workstreams.md#assignment-and-handoff-rules) | Baseline, active owner, dependency and acceptance record. These own current scope. |
| [Contracts](../src/research_assistant/contracts.py), [Store](../src/research_assistant/store.py), [Application](../src/research_assistant/application.py) | Existing types/lifecycle before proposing a new boundary. Preserve old records and idempotency. |
| [Git worktrees](https://git-scm.com/docs/git-worktree), [SQLite transactions](https://www.sqlite.org/lang_transaction.html) | Isolation and transaction reference when the assigned change needs it; no new service required. |

### R1 SEC filings and financial calculations

| Required reference / data | Use and acceptance boundary |
|---|---|
| [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [developer/access guidance](https://www.sec.gov/about/developer-resources) | Submissions/company-facts endpoint semantics, client identification and access rules. Current direct SEC path is integrated; original filing packets remain planned. |
| [MSFT submissions](https://data.sec.gov/submissions/CIK0000789019.json), [MSFT company facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json), [EDGAR company filings](https://www.sec.gov/edgar/browse/?CIK=789019&owner=exclude) | Locate the actual FY2024 10-K accession and its primary document/table; cross-check two values. Current endpoints change, so retain bytes and retrieval time. Resolve the exact filing URL rather than inventing an accession. |
| [Microsoft FY2024 annual report](https://www.microsoft.com/investor/reports/ar24/index.html) | Issuer cross-check for statement names, annual dates and scale; SEC accession remains the filing identity. A company-hosted page is a separate source, not proof of the stored SEC bytes. |
| [SEC Inline XBRL overview](https://www.sec.gov/structureddata/osd-inline-xbrl.html), [XBRL specifications](https://specifications.xbrl.org/) | Context, units, scale, duration/instant and dimensions. Consult for the narrow fields used; do not start by implementing a complete XBRL engine. |
| [Decimal](https://docs.python.org/3/library/decimal.html), [Pydantic validation](https://docs.pydantic.dev/latest/concepts/validators/), FinanceToolkit in the catalogue | Arithmetic/validation references; financial formulas still need independently checked aligned inputs. Reuse installed Pydantic/standard-library Decimal. |

**Packet inventory:** source identity/accession; original document bytes and hash; table title/row/column locators; raw display values and scale; normalized USD values; duration and scope/basis; original availability and retrieval time; company-facts comparison; formula and result; checker/discrepancy notes. Two checked facts in one filing are a pilot, not proof of general extraction accuracy. Store shareable test packets separately from private/live data.

### R2 Model contracts and provider access

**Maintenance pack:** the live-access checkpoint and qualitative-output fix are complete; current evidence is in [STATUS](../STATUS.md#recorded-checks). Consult this pack for a concrete new failure or agreed provider/model change. General reliability measurement belongs to C5.

| Required reference / local material | Use and acceptance boundary |
|---|---|
| [Saved live attempts and outcomes](../STATUS.md#recorded-checks), [model checks](../tests/test_model_checks.py), [model access tests](../tests/test_model_access.py) | MSFT and post-fix AAPL pairs have saved responses and completed review records. The original failed answer was not retained; its exact cause remains unknown. For a new failure, inspect retained output/metadata and reproduce offline before another paid call. |
| [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [function calling](https://developers.openai.com/api/docs/guides/function-calling), [Python SDK](https://github.com/openai/openai-python) | Completed/refused/incomplete results, schema parsing and tool boundaries. A valid schema still needs claim/evidence membership validation. |
| [OpenRouter Responses API](https://openrouter.ai/docs/api_reference/responses/overview), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) | Verify the selected model/endpoint actually supports the required request. Recheck current docs/settings before a live attempt; keep fixed routing and usage records. |

Existing evidence includes mocked failure/valid-pair coverage and dated live pairs with reported usage/cost. A reopened failure task should add a fixture for the newly observed response and focused regression proof; repeat live checks only when needed and authorized. Existing model access is configured separately from Codex subscriptions. Credentials stay local; mock success establishes software behavior only.

### R3 Company identity and screening

| Required reference / data | Use and acceptance boundary |
|---|---|
| [SEC company tickers](https://www.sec.gov/files/company_tickers.json), [ticker/exchange directory](https://www.sec.gov/files/company_tickers_exchange.json), R1 submissions docs | Candidate current identity directory; inspect actual schema, aliases/share classes and availability. Save a dated snapshot. Neither file supplies a historical index or validated sector taxonomy. |
| [Current identity/request types](../src/research_assistant/contracts.py), [screening](../src/research_assistant/screening.py), [Research extraction](../src/research_assistant/research.py) | Trace every five-company restriction and UNIVERSE lookup before extending identity. Preserve saved issuer identity and explicit unknown coverage. |
| FinanceDatabase in the catalogue | Optional broader metadata only when SEC lookup is insufficient. Inspect refresh/cache behavior and licence before adoption; avoid adding it for an unused field. |

Required output is one outside-five company report and a saved 1–10-company screen, including unavailable financial/sector cases. Declare how share classes map to issuer-level financials; do not double-count an issuer accidentally.

### R4 Review and correction

| Required reference / local material | Use and acceptance boundary |
|---|---|
| [Next record boundary](design.md#next-implementation-boundary), [Application](../src/research_assistant/application.py), R1 checked facts/calculations | Define target version → allowed check → resolution evidence → disposition; invalidate dependent values before re-screening. |
| [Du et al., multi-agent debate](https://proceedings.mlr.press/v235/du24e.html), [Kaesberg et al.](https://aclanthology.org/2025.findings-acl.606/) | Research motivation and comparison ideas. Read methods/limitations before transferring a claim to financial evidence review. |
| [AgentDojo](https://arxiv.org/abs/2406.13352), TradingAgents in the catalogue | Useful-task/injection cases and optional workflow baseline. Pin any reused revision and control cross-run memory. |

Required output is changed, unchanged and unresolved traces plus a threshold-crossing discovery example. Generic agreement between agents and empty objections are not resolution evidence. Do not adopt an orchestration framework to obtain these transitions.

### R5 Research evaluation

| Required reference / data | Use and acceptance boundary |
|---|---|
| [Evaluation protocol](design.md#how-to-evaluate-research), R1 checked packets, R4 correction cases | Primary in-domain case matrix: financial correctness, citation support, coverage, harmful revision and candidate selection. Use human/independent label checks. |
| [FinQA repository](https://github.com/czyssrs/FinQA), [FinQA paper](https://aclanthology.org/2021.emnlp-main.300/), [TAT-QA repository](https://github.com/NExTplusplus/TAT-QA) | Optional numerical/table reasoning component tests. Inspect split/licence, answer/program fields and possible model contamination; they do not replace original-filing or Discovery cases. |
| [AgentDojo](https://arxiv.org/abs/2406.13352), debate/review papers in R4 | Failure/injection categories and review ablations; task utility and security both matter. |
| [SciPy bootstrap reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) | Method reference if used for paired uncertainty; resample task/case clusters together rather than treating related claims as independent samples. A new dependency is optional, not required by the rubric. |

**Evaluation inventory:** versioned protocol; development and held-out manifests; source bytes/hashes and cutoffs; separate checked answers/rubric; double-label/disagreement log; model/prompt/schema settings; fixed budgets and initial drafts; raw runs; numerical/semantic scores; coverage/harm/cost/latency tables; uncertainty and failed-run rules; reproduction command. Choose sample counts before the run; a small sample must stay labelled exploratory.

### R6 UI and browser verification

| Required reference / local material | Use and acceptance boundary |
|---|---|
| [UI contract](../verification/design-contract.md), [browser scenarios](../frontend/tests/workspace.spec.ts), [Playwright config](../frontend/playwright.config.ts) | Existing interaction, focus, mobile, injection and recovery patterns. Fixed port 8000 means concurrent browser runs need coordination. |
| [React](https://react.dev/learn), [Playwright assertions](https://playwright.dev/docs/test-assertions), [accessibility testing](https://playwright.dev/docs/accessibility-testing) | Implement and test only the feature's interactions; existing dependencies already include React/Playwright/axe. |
| [WAI-ARIA authoring practices](https://www.w3.org/WAI/ARIA/apg/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Keyboard/focus/status semantics; prefer native controls and semantic HTML. Automated scans supplement visual/keyboard checks. |

Required output is focused browser proof plus visually inspected desktop/mobile captures. API mocks label software behavior; they are not live financial or provider proof.

### R7 Reproducibility and academic delivery

| Required reference / local material | Use and acceptance boundary |
|---|---|
| [Course guideline](../../COMP7608B_LLM_Project_Guideline.pdf), [original scope](archive/implementation_plan.md) | Check actual deliverables against the guideline; confirm deadline/final report format with the group/course. Archived plans are context, not new requirements. |
| [README setup and backup](../README.md#setup-and-development), [launcher](../start.ps1), [recorded checks](../STATUS.md#recorded-checks) | Clean-environment setup, whole-data stopped-server backup/restore and dated proof. Preserve current local server/user data. |
| [Evaluation protocol](design.md#how-to-evaluate-research), C5 experiment artifacts | Every result/table/demo claim traces to saved evidence. Distinguish implementation success from research quality and investment performance. |

**Delivery inventory:** runnable code and locked dependencies; setup commands; shareable real/synthetic packets; backup/restore notes; experiment configs/scripts/raw results; final report figures/tables; demo script/captures; limitations/cost/rights statement; task contributions if required. Final submission location/format remains to be confirmed.

### R8 Wider discovery and events

| Required reference / data | Use and acceptance boundary |
|---|---|
| R3 directory/saved universe, R1 submissions/filing retrieval | Bounded candidate generation and dated eligible evidence; search breadth and actual evaluated coverage are separate counts. |
| [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf), issuer annual reports and investor-relations releases | First event/material-risk sources. Save exact item/exhibit/text and publication/availability dates; management statements retain attribution. |
| [SEC Inline XBRL](https://www.sec.gov/structureddata/osd-inline-xbrl.html), FinQA/TAT-QA from R5 if tables are involved | Reference for structured/qualitative extraction boundaries. Risk-section retrieval does not prove complete risk coverage. |

General news requires a specific provider/rights decision, duplicate-source rules and independent evaluation. A connector visible in an agent client is not an integrated application feed or a data licence.

### R9 Prices and forecasting

| Required reference / data | Use and acceptance boundary |
|---|---|
| [Proposed forecast protocol](design.md#how-to-evaluate-research), price-provider candidates in Data choices above | Freeze the target first; validate one source's actions/adjustments/history/storage rights before training. Recheck advertised access and prices at selection time. |
| [NYSE calendars](https://www.nyse.com/markets/hours-calendars), [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) | Official session cross-check and a candidate calendar dependency. Validate supported market/date range and release; a calendar does not supply prices. |
| [Logistic regression](https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression), [calibration](https://scikit-learn.org/stable/modules/calibration.html), [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [Brier score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html) | Simple baseline, reliability and split/scoring references. Freeze binary score scaling/version; enforce matured labels and session-aware panel purging explicitly. |
| Qlib, ML4T, TA-Lib and QuantStats in the catalogue | Later optional comparison/helpers. None grants price access or turns forecast accuracy into trading performance. |

**Forecast inventory:** one-provider acceptance sample; split/dividend checks; raw/adjusted fields and calendar; dated universe/coverage; target/feature versions; matured labels; training/validation/test dates; trial registry; immutable p0; probability/coverage/uncertainty results. Defer prospective performance claims until forecasts were actually logged before their anchors.

### R10 Factors and other later research

| Reference | Use and entry boundary |
|---|---|
| [Fama–French factor definitions](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html), [factor families](#factors) | Distinguish company features, risk exposures, factor returns and model-relative alpha. |
| [Qlib](https://github.com/microsoft/qlib), [ML4T Engineer](https://github.com/ml4t/engineer), [vnpy](https://github.com/vnpy/vnpy) | Optional feature/model experiment references after C9. Inspect actual data/version/licence; use only for a declared hypothesis. |
| [The Probability of Backtest Overfitting](https://arxiv.org/abs/1407.0340), [The Deflated Sharpe Ratio](https://ssrn.com/abstract=2460551) | Multiple-trial/selection concerns for factor or strategy research; disclose searched trials and retain an untouched test. Reading a method does not validate the experiment. |
| [FRED/ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | Historical vintage boundary for a separately scoped macro feature. New market/currency/accounting coverage needs its own acceptance packet. |

Portfolio execution, broker integration and public multi-user hosting need separate specifications. No resource in this pack creates an outstanding core requirement or authorizes trading.

## Primary reading

| Source | Why read it |
|---|---|
| [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and [access guidance](https://www.sec.gov/about/developer-resources) | Endpoint coverage, client identification and fair access; not validation of our selection algorithm |
| [Du et al.](https://proceedings.mlr.press/v235/du24e.html), [Kaesberg et al.](https://aclanthology.org/2025.findings-acl.606/) | Motivation to test bounded review; neither proves investing skill |
| [FinQA](https://github.com/czyssrs/FinQA) | Numerical reasoning component benchmark; keep gold programs/support indices out of inputs |
| [Calibration guide](https://scikit-learn.org/stable/modules/calibration.html), [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) | Scores, reliability and split mechanics; panel label purging still needs explicit checks |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | Test useful work alongside resistance to instructions embedded in sources |
| [FRED/ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | Historical vintages if macro features are later added |

<details>
<summary>Review history and academic constraints</summary>

The [full source audit](archive/source_audit.md) preserves earlier methodological findings, additional reading and exact review limits. The [alignment review](archive/alignment_review_2026-10-25.md) records accessible project chats; some older assistant replies and proposal/diagram attachments were unavailable.

The local [course guideline](../../COMP7608B_LLM_Project_Guideline.pdf) calls for a runnable agentic application, meaningful tool decisions, evaluation and limitations; multi-agent organization is optional. It specifies a 3–5-person group. The proposal's four-page NeurIPS/no-abstract format does not establish the final report format. Final deadline, current group availability and experiment budget remain unconfirmed; the old four-week allocation is historical planning.

</details>
