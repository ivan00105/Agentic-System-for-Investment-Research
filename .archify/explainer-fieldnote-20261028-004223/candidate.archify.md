# Fieldnote: current system and next steps {#fieldnote}

Fieldnote now supports financial research without a model, optional OpenRouter review, and explicit connection checks. Broader company search and automatic research correction are the next stages.

@answer scope="28 Oct 2026 · working tree · live checks deferred"
@meta locale=en style=clean quality_profile=showcase
@source app title="Inspected application.py:94–355; saved copy in evidence/"
@source model title="Inspected model_access.py:25–143 and contracts.py:43–77; saved copies in evidence/"
@source data title="Inspected research.py and screening.py; saved copies in evidence/"
@source storage title="Inspected store.py:13–155 and api.py:44–119; saved copies in evidence/"
@source ui title="Inspected frontend App.tsx and api.ts; saved copies in evidence/"
@source plan title="STATUS.md and docs/design.md at inspection; saved copies in evidence/"

## What runs today? {#architecture span=12}

@architecture id=system-map title="One local application with conditional external calls"
| browser | Research workspace | frontend |
| api | Local API | backend |
| worker | One Python worker | backend |
| store | Store | backend |
| sqlite | SQLite | database |
| files | Source snapshots | database |
| sec | SEC annual facts | external |
| model | Selected model provider | external |
| browser > api | HTTP |
| api > worker | enqueue |
| api > store | saved reads |
| worker > store | read/save |
| store > sqlite | transactions |
| store > files | source bytes |
| worker > sec | fresh only |
| worker > model | requested review |

Python owns source selection, calculations, allowed checks and run limits. Store owns SQLite and snapshot writes. The API, worker and Store share one process.[](source:app) [](source:data) [](source:storage)

| Connection | Current behavior |
| --- | --- |
| SEC | Annual USD financial facts for five supported companies; live access remains unchecked |
| Optional model | OpenAI, OpenRouter or a trusted compatible endpoint; structured interpretation and critic responses are validated |
| Configuration | Server environment only; restart after changes; credentials stay on the server |
| Connections page | Shows setup and current-session outcomes; opening or refreshing starts no provider calls |
| Explicit tests | SEC uses MSFT without a model; model test uses saved evidence with consent, an allowance and provider-cap confirmation |

Requests have no automatic paid retries or provider fallback. Reported usage is saved, including when output validation fails. Missing cost remains unknown. The allowance cannot guarantee a billing cap.[](source:model) [](source:app) [](source:ui)

@callout level=note title="Evidence scope"
| This page describes inspected, uncommitted files. Source copies and hashes are in evidence/; they are not presented as committed HEAD bytes. |
| Implementation and mocked tests do not establish live access or financial correctness. Saved teaching examples and corrections remain synthetic. |

## What happens to a request? {#current span=12}

@diagram workflow id=current-flow source=current-flow.json title="Current workflow · optional review and saved financial results"

| Path | Result |
| --- | --- |
| Replay | Reopens saved evidence and output; no retrieval or model calls |
| Fresh | Retrieves eligible SEC facts and computes metrics; SEC contact setup is required |
| Frozen | Reuses the saved company, cutoff, evidence and metrics; new model analysis is optional |
| Discovery | Screens five companies by sector and annual margin; eligible selection is alphabetical |
| Model off, unavailable or failed | Financial results remain available; model status is separate |
| Critic objection | Records unresolved concerns and host checks; no automatic correction |
| Failure or shared limit | Preserves available partial results; no automatic retry or resumption |

The review path repeats for each selected company. Unknown values cannot pass a required filter. Recovered submissions reuse their original request and key.[](source:app) [](source:data) [](source:ui)

## How does the research loop evolve? {#target span=12}

@workflow id=target-flow title="Planned correction path · bounded review before reporting"
| lane inputs | Evidence and draft |
| lane review | Review and permitted checks |
| lane results | Resolution and output |
| scope | Research scope | frontend | inputs |
| facts | Sources and facts | database | inputs |
| draft | Draft claims | backend | inputs |
| audit | Risk review | security | review |
| follow | Follow-up needed? | backend | review |
| checks | Allowed checks | backend | review |
| resolve | Resolve and version | backend | results |
| screen | Recalculate and screen | backend | results |
| brief | Research brief | frontend | results |
| scope > facts | |
| facts > draft | |
| draft > audit | |
| audit > follow | |
| follow > checks | yes |
| follow > brief | no |
| checks > resolve | result |
| resolve > screen | changes |
| screen > brief | |

The coordinator routes filings/events/quant work and synthesis within one application. Repeat review only within the shared budget; unresolved results retain their concerns. Dedicated event research remains planned.[](source:plan)

| Planned boundary | Required behavior |
| --- | --- |
| Evidence and calculations | Preserve original tables, typed facts, formula inputs and source dates |
| Correction loop | Target claim versions, run allowed checks, preserve resolutions, recalculate affected results and re-screen Discovery |
| Separate forecasting | Validate a price model and score mature outcomes; narrative review cannot change its probability |

## How do we reach broader Discovery? {#next span=12}

The five companies are today's supported universe and also have synthetic examples. SEC directory search will broaden identity lookup. Financial evidence and filters determine eligibility.[](source:plan) [](source:data)

| Next checkpoint | User-visible result |
| --- | --- |
| 3 · Original filing | Compare two saved Microsoft FY2024 figures with the original table |
| 4 · Validated calculations | Inspect a correct margin and a rejected company, period, currency or scope mismatch |
| 5 · Company search | Research a supported US filer outside the original five using the SEC directory |
| 6 · Selected-list Discovery | Screen up to ten selected companies; see passes, failures, unknowns and actual coverage |

Wider automatic candidate sourcing follows these checkpoints. Add prices, events or news when a research question needs them; directory membership alone cannot rank a company. Live checks remain deferred under the setup-only choice.[](source:plan)

- [ ] Restart Fieldnote and inspect Connections without starting a test.
- [ ] Inspect a report with model analysis off; financial results should remain usable.
- [ ] Use STATUS.md as the single implementation checklist.
