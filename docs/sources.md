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

Access and advertised prices checked **27 October 2026**; documentation updated **28 October 2026**. Account eligibility, live quality and demonstration rights remain unverified. No data subscription is required for the current milestone; optional model calls may incur charges.

| Need | Initial choice / alternatives | Cost or acceptance boundary |
|---|---|---|
| Filings / accounting | Direct [SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces); original filing/table retrieval follows | Public access without an API key; contact identity required. Validate accession, dates, units and original table. |
| Company directory | Searchable SEC US directory planned after original filing evidence and typed validation; FinanceDatabase later for broader metadata | Current universe is five mappings. Directory identity/search is not financial evidence or ranking. Save the selected list/date; current metadata is not historical membership. |
| Optional model review | OpenAI, [OpenRouter](https://openrouter.ai/docs/api_reference/responses/overview), or a trusted compatible endpoint | Explicit server environment configuration and model choice; model check needs saved evidence, consent, a positive allowance and provider/key spending-cap confirmation. App limits cannot guarantee a dollar cap; missing reported cost remains unknown. Live access is unverified. |
| Historical prices | Evaluate [Massive](https://massive.com/pricing) when price research begins | Free individual tier advertises two years of end-of-day history and five calls/minute. Validate splits/dividends and usage rights. |
| Longer price history | Compare [EODHD](https://eodhd.com/pricing) and educational access | Free: one year, 20 calls/day. EOD plan: US$19.99/month; student discount advertised. Data quality and rights still require checking. |
| Financial/price alternative | [Alpha Vantage](https://www.alphavantage.co/support/) | Standard free: 25 calls/day; verified educational projects may receive more. [Daily adjusted prices](https://www.alphavantage.co/documentation/#dailyadj) require premium access; extra quota does not prove endpoint entitlement. |
| Personal price prototype | [yfinance](https://ranaroussi.github.io/yfinance/) | Free software, unofficial access and personal-use data limitations. Not a guaranteed service or redistribution licence. |
| Macro, later | [FRED/ALFRED](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | API key required; retain historical vintages rather than using today's revised values in past decisions. |
| Events / news, later | Eligible SEC 8-Ks/exhibits and issuer material first; general news deferred | Save source text and publication time; confirm content rights before adding a news service. |

No authenticated price/news/model entitlement or free-tier budget was established. No silent provider switch is permitted. Evaluate required coverage, adjustments, storage/replay and sharing rights before price. FinanceDatabase's inspected cache refreshes daily and can return older cached data on download failure: preserve a dated snapshot if adopted. A company announcement supports attribution to management, not the truth of a future outcome; syndicated stories are not independent confirmation.

The next data milestones are one independently checked original annual filing packet, typed fact/calculation validation, broader company search, then a real financial screen over up to ten user-selected companies. Wider automatic candidate sourcing comes later. These steps do not require installing every listed integration; add price history or news when a defined research task needs it.

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
