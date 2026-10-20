# Correctness audit and resource decisions

Checked 18 October 2026, Hong Kong time. Read alongside the [implementation plan](./implementation_plan.md).

Implementation note, 19 October: the custom-web milestone now exists under [stock_research](../../README.md). The audit statements below describe the earlier source review, not validation of the new application. Current SEC/model live access remains unverified; synthetic replay and mocked transport tests must not be cited as evidence of real provider access or investment performance.

## 1. What was actually checked

I read the final response in the [shared ChatGPT conversation](https://chatgpt.com/share/6ad4955b-b618-83ea-afcc-303b0e8e8767) through its browser view, along with the conversation context visible there. I also extracted the local course guideline and inspected all ten linked repositories plus the linked arXiv directory. Relevant methodological claims were checked against primary papers and official documentation.

This is a documentation and methodology review, not a code-security audit or independent reproduction of the repositories' experiments. No project packages were installed or benchmarked. Repository READMEs describe intended/current functionality; they do not establish that every implementation path is correct.

The original/revised/FINAGENT/FIN/BAK proposal files and the previous answer's downloadable plan/ZIP/PDF were not present in the local workspace and were not inspected. Consequently, its judgments about which draft is better, diagram overlaps, duplicate documents, fallback LaTeX styles, compilation success and page count remain **unverified**. This review does not repeat them as established facts.

## 2. Audit of the last response

| Earlier statement or recommendation | Verdict | Implementation consequence |
|---|---|---|
| Research and discovery can share the same engine | Sound architecture recommendation | Keep a single candidate-research function; discovery adds screening, scheduling and aggregation. |
| Five logical roles, coordinator also acting as synthesizer/arbiter | Reasonable, not experimentally optimal | Use roles within one bounded workflow; compare with a single-agent baseline. |
| A critic should name claims, request checks and record outcomes | Sound and testable | Store objections against claim versions, correction evidence and unresolved issues. |
| The critic may find no valid objection | Important | Include clean cases; measure false objections and damaged correct claims. |
| Debate sometimes improves reasoning/factuality but does not establish better investment forecasts | Supported, appropriately qualified | Treat review benefit as a hypothesis and measure it locally. |
| Discussion protocol and length affect performance | Supported in evaluated benchmark settings | Two rounds is a practical cap, not a universal optimum. |
| Identical probabilities imply identical Brier scores | Mathematically correct on identical cases/weights | Separate forecast evaluation from report quality; disclose abstention-driven sample differences. |
| An unchanged objection count is an inadequate stopping rule | Correct | Track identities, claim versions, resolution evidence and budget exhaustion. |
| A valid schema does not establish factual truth | Correct | Add provenance, numerical checks and independent semantic assessment. |
| Outperforming SPY differs from positive return or a profitable trade | Correct | A stock losing 2% beats SPY losing 5%; neither establishes a trading profit. |
| Historical document filtering cannot eliminate LLM training leakage | Correct limitation | Preserve historical source controls but avoid claiming a clean historical LLM forecasting test. Begin prospective logging. |
| Portfolio returns/Sharpe can wait | Correct for this product | Probability and research-task evaluation do not need positions. Sharpe requires an actual return series with a defined strategy if used as strategy performance. |
| Five companies, later about 30; four-week schedule | Planning assumptions | Confirm feasibility, quota and deadline; do not present these numbers as optimal or official. |
| Multi-agent collaboration is optional; runnable end-to-end application and evaluation are required | Confirmed against local guideline | Prioritize meaningful conditional actions over the number of agent labels. |
| NeurIPS 2026 template, four main pages, no abstract | Confirmed for the proposal in local guideline | Does not establish the final report format, which remains TBA in that document. |
| Revised proposal files/diagrams were faulty; replacement compiled correctly | Not independently verified | Need those actual files to audit these artifact-specific claims. |

The empirical debate claims have appropriate primary support. [Du et al., ICML 2024](https://proceedings.mlr.press/v235/du24e.html) study factuality and reasoning across their selected tasks. [Kaesberg et al., Findings of ACL 2025](https://aclanthology.org/2025.findings-acl.606/) compare decision protocols and report task-dependent effects, including deterioration with additional discussion rounds in their setting. Neither result alone proves that financial research accuracy or investment forecasts improve in this application.

The [local course guideline](../../../COMP7608B_LLM_Project_Guideline.pdf) also confirms a 3–5-person group and assessment weights of 20% proposal, 50% report/code and 30% presentation. It contains inconsistent proposal deadline wording: 9 October at 24:00 in one table and noon Hong Kong time in the proposal section. That date has passed as of this review; the document does not establish the current final delivery deadline. Check the current course announcement rather than inferring a date from the proposed four-week plan.

## 3. Details that need strengthening

**Historical availability must be enforced at the data boundary.** Period end, publication/acceptance, retrieval, first observation and revision time mean different things. An `as_of` field attached by a model is not a historical-data guarantee. Archive the source version and record why it was eligible. Current financial summaries and mutable news pages cannot automatically be used in a historical simulation.

**The forecast target needs an exact interval.** The earlier answer specifies 20 trading sessions and SPY but leaves price anchor, issuance time, dividend convention, ties and unresolved outcomes unspecified. The implementation plan proposes next-session close to 20 sessions later, with issuance before the anchor. This is a new design choice, not a recovered detail from the old answer.

**Time separation must follow label maturity.** A training row dated before a test date can still have a future 20-session outcome crossing into the test period. Split all stocks by date and check outcome availability, not just row order. The standard [TimeSeriesSplit API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) does not by itself implement panel-aware label purging.

**Brier score is not a pure calibration measure.** It reflects more than reliability. Add reliability plots with bin counts and compare with training-only base rates. The [scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html) explicitly explains why lower Brier loss need not mean better calibration.

**Forecast probability is not research confidence.** A well-supported report can contain a weak forecast. Conversely, sparse filings do not necessarily invalidate a price-only statistical forecast. Display evidence support and forecast status separately, and do not let prose imply that excluded information changed the number.

**Evidence quality is not the number of links.** A cited sentence may not support the conclusion. Duplicated news is not independent corroboration. A company's forward-looking statement supports attribution to management, not the future outcome. Evaluate entailment, entity, period and scope.

**The experiment needs a strong compute-aware baseline.** Comparing a multi-call workflow only with a one-shot answer confounds orchestration with more computation and more evidence. Include one tool-using agent and a same-draft self-review condition. Record actual usage as well as equal caps.

**Discovery adds its own correctness obligations.** Define supported filters, unknown values, ranking, replacement, candidate budgets and the declared universe. The final answer should be allowed to contain fewer candidates than requested. Ranking outcomes need comparison to the same deterministic screen/statistical ranking without narrative review.

**Survivorship and model knowledge are separate issues.** Historical membership is needed for market-wide universe claims; historical source snapshots are needed for evidence eligibility; model training chronology is a further limitation. Fixing one does not solve the others. The plan deliberately bounds the initial historical claim to a selected-company study.

## 4. Decisions on every supplied resource

These are recommendations for this particular stock-research application, not rankings of overall project quality. Current features can change; pin a commit/version before incorporating code and test the exact functions you use.

| Resource | What it supplies | Decision for this system | What not to assume |
|---|---|---|---|
| [awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | Broad directory of numerical, financial, data, calendar and backtesting tools | Keep as a lookup index when a concrete implementation gap appears | Being listed does not validate a package's correctness, maintenance, data rights or historical fidelity. |
| [Quant-Developers-Resources](https://github.com/cybergeekgyan/Quant-Developers-Resources) | Learning and career/interview resources across quantitative finance and engineering | Background study only; no runtime dependency | It is not a ready data pipeline or research-agent framework. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Role-based financial research/trading framework using LangGraph | High-value architecture reference and possible later external baseline; inspect selected patterns instead of adopting the whole stack | Its returns and research results do not transfer to this project or prove a general trading advantage. |
| [quant-mind](https://github.com/LLMQuant/quant-mind) | Typed financial knowledge extraction/retrieval, with paper/news workflows and provenance concepts | Borrow source-first document/card concepts; assess extraction components only if a measured gap remains | Its README lists SEC/filings collection as not yet shipped. It is not a drop-in SEC backend. |
| [Introduction-to-Quantitative-Finance](https://github.com/Barca0412/Introduction-to-Quantitative-Finance) and [arXiv radar](https://barca0412.github.io/Introduction-to-Quantitative-Finance/arxiv/) | Tutorials, topic/resource collections, and a paper-discovery interface | Useful for related work and identifying original papers/benchmarks | Automated tags/summaries are discovery aids, not primary evidence or peer review. |
| [awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | Systematic-trading resources and strategy references | Use for future baseline ideas and backtesting cautions; defer strategy implementation | Attractive published/replicated returns do not establish out-of-sample performance for this universe or time window. |
| [QuantStats](https://github.com/ranaroussi/quantstats) | Return-series analytics, risk/performance plots and HTML reports | Defer until a defined strategy/portfolio return series exists | It does not create valid fills, remove leakage, or evaluate citation correctness. It is not needed for Brier score. |
| [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) | Instrument symbols and descriptive metadata | Potential one-time universe/identity seed, followed by manual validation and versioning | It explicitly is not an up-to-date fundamentals/price database; a current catalog is not historical membership. |
| [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | Financial ratios, indicators and analysis functions with data integrations | Useful formula reference or selected checked calculations over your normalized inputs | Provider coverage and accounting definitions still need validation. Its documented FMP→Yahoo fallback can change provenance unless controlled. |
| [OpenBB](https://github.com/openbq-org/OpenBB) | Data integration platform connecting multiple sources to downstream applications | Conditional choice if several providers demonstrably justify a shared integration layer; unnecessary for SEC plus one price source initially | An integration platform does not grant underlying data subscriptions, licences or point-in-time correctness. |

The formerly common [OpenBB-finance/OpenBB URL](https://github.com/OpenBB-finance/OpenBB) redirected to the user-supplied `openbq-org/OpenBB` repository during this check. The supplied link is therefore not a typo that needs replacing based on older documentation.

TradingAgents' current README describes dated-data handling and newer backtesting behavior. Those are useful areas to inspect, but this review has not exercised or audited those implementations. If used as a baseline, pin the repository revision, disable or isolate cross-run memory, use the same eligible evidence/cutoff, and align the output target. Its [research paper](https://arxiv.org/abs/2412.20138) evaluates a different trading framework; a full implementation replication is optional and should not delay the core application.

QuantMind's typed provenance ideas fit well, but even its own timestamped artifacts still require a source-availability policy. Its current [README roadmap](https://github.com/LLMQuant/quant-mind#-roadmap) identifies filings collection as future work. The economical choice is to implement the small SEC path directly and reuse only components that pass a local fit test.

For FinanceToolkit, enforce one chosen source or supply validated input data. Do not silently replace missing historical fundamentals with current Yahoo statements. Verify ratio formulas, period transformations and missing-value behavior against hand calculations. The [README](https://github.com/JerBouma/FinanceToolkit) documents configurable source enforcement; this is a useful control, not proof of data correctness.

Do not add all these packages. The initial dependency set can remain ordinary Python data/model/UI tooling, a small SEC integration, and one price adapter. Add a project-specific library only when it reduces implementation and maintenance work without obscuring the invariants.

## 5. Data-source decision matrix

| Need | Initial source | Required feasibility proof | Fallback |
|---|---|---|---|
| Filing metadata and evidence | SEC submissions and archived filings | Five issuers, accepted timestamps, table evidence and amendment handling | Frozen eligible filing fixtures; clearly expose missing extraction |
| Structured accounting facts | SEC company facts plus filing context | Correct tag, unit, period and accession for manually checked metrics | Parse the specific eligible filing table; otherwise unavailable |
| Price/benchmark history | One selected daily-price provider | Coverage, splits, dividends, session dates, adjustment behavior and usage rights | Authorized cached research data; no silent provider switch |
| Universe metadata | Hand-curated manifest, optionally seeded by FinanceDatabase | Correct listing/CIK mapping, declared selection date and scope | Maintain the five-company manifest manually |
| Events | SEC 8-Ks/exhibits and verified dated issuer materials | Availability timestamps and source text | Report limited event coverage |
| General news | One provider only after a coverage/access test | Historical retention, article versions, content rights and cost | Filing-based events remain the initial supported scope |
| Macro, if later needed | FRED/ALFRED vintage-aware data | Observation value as known at each cutoff | Omit macro features rather than use revised data incorrectly |

The [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) establishes the available submissions/fact interfaces and their coverage limitations; it does not certify the team's fact selection algorithm. [SEC fair-access guidance](https://www.sec.gov/about/developer-resources) also applies to automated retrieval.

[FRED's real-time-period documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) distinguishes today's view of historical data from information known at earlier dates. Macro can be omitted in version 1, avoiding a separate revision-management problem.

Provider free tiers, historical coverage, commercial terms and news access were not validated through authenticated accounts. Do not budget around a README's quoted free-plan limits. Test actual accessible endpoints first. Package licence, provider terms and rights to redistribute cached data are separate questions; no repository-level licence supplies all three.

## 6. Sources worth adding to the group's reading list

| Primary source | Why it matters | Limit of its relevance |
|---|---|---|
| [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Authoritative endpoint/coverage context for filings ingestion | Does not solve period matching and evidence selection for you |
| [Du et al., multiagent debate](https://proceedings.mlr.press/v235/du24e.html) | Motivation for an empirical review experiment | Does not prove investing skill |
| [Kaesberg et al., voting or consensus](https://aclanthology.org/2025.findings-acl.606/) | Motivation to bound and control the decision protocol | Effects are benchmark-dependent |
| [FinQA](https://github.com/czyssrs/FinQA) | Financial numerical reasoning with reference programs and evidence | Component benchmark, not full-system evaluation |
| [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html) | Probability interpretation, proper scores and reliability plots | Software documentation, not evidence that the proposed model predicts returns |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | Testing utility and prompt-injection resistance together | Adapt the idea to financial-source fixtures; full benchmark reproduction is unnecessary |

The practical additions are mostly correctness mechanisms, not more agents: historical source versions, claim/calculation lineage, hard screening semantics, label-maturity checks, review-damage measurement, and explicit fresh/cached/replay modes. Those additions make the system easier to defend in a live demonstration and a technical report.
