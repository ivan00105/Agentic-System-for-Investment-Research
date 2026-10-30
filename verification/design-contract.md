# Fieldnote UI contract

Purpose: inspect a stock-research result, its source evidence, and the change caused by review. Audience: a course demonstrator and an evaluator who needs to distinguish a supported calculation from a persuasive narrative.

Primary action: open a saved teaching example or explicitly submit a new investigation. The first screen is the application. Hierarchy: controls → run mode and cutoff → report → claim/source link → correction → separate forecast → limitations → activity log.

26 October presentation update: use plain action names and progress labels. Keep source dates, inputs, interpretations, synthetic status, corrections and unresolved concerns visible. Put hashes, raw locators and detailed activity behind disclosure; show unavailable forecasts as a short notice. Record types, version numbers, polling mechanics and setup commands do not belong in the main report.

Visual direction: compact editorial research desk, warm neutral surfaces, forest-green actions, amber qualifications, aligned numerical columns and restrained typography. A source desk beside the report is the memorable interaction. Local product requirements establish these choices; no external design service or assets are used.

Target viewports: 1440x900 and 390x844. On narrow screens the source desk is an inline section. Citation activation focuses the source heading; closing returns focus to the triggering citation. Tables scroll inside their own region. Long source IDs wrap. Controls use visible focus and text labels; status does not rely on colour. Reduced motion removes progress animation.

Content states:

| State | Trigger | Feedback and safe next action |
|---|---|---|
| Loading | Run/source/history fetch pending | Named loading message; no invented progress percentage |
| Empty | Research opened without a run | Explain first action and offer labelled teaching example |
| Error | Missing ID, configuration or network | Specific message; retry connection or choose new input; no automatic paid retry |
| Partial | Some figures missing or requested model analysis fails | Available figures remain usable; financial availability and model status shown separately |
| Success | Stored result available | Financial completion can occur without model analysis; source labels, citations and history remain visible |
| Permission | Cross-site access blocked | API returns an explicit local-only 403; no login/permission UI exists in this single-user milestone |

Verification: browser screenshots, accessible names, keyboard skip/focus, axe checks, no document horizontal overflow, long-content injection fixture, reduced motion, reconnect and idempotency tests. The bundled frontend skill checker validates the evidence record; it does not replace visual inspection.

28 October Connections checkpoint: the Connections view separates environment setup (Configured / Not configured) from the latest finished genuine provider attempt in the current server session (Not tested / Check passed / Check failed). SEC financial data and optional model analysis have separate cards. Attempt time and a saved-investigation link are shown when recorded; the link resolves research or discovery before opening the saved result. A successful attempt does not establish financial correctness. Fixture replay and stored history do not establish connection status.

Entering Connections and refreshing status only read configuration and saved sources. Explicit Test SEC connection probes MSFT annual facts without model calls. Test model connection uses a selected terminal research packet with evidence, retains its original ticker and cutoff, and allows at most one interpretation/critic pair. Sources distinguish synthetic teaching data from real saved research. The model form starts with an empty positive USD allowance and unchecked consent acknowledging evidence sharing, possible charges and a provider/key spending cap. Source or allowance changes reset consent. The allowance is not a guaranteed application dollar cap. Missing provider setup disables the corresponding check. No credential inputs or writable server settings are offered.

Before submission, persist the exact check request and idempotency key in the separate fieldnote-pending-check session record. Unknown outcomes disable edits and new tests; only explicit Retry same submission recovers the same intent, including after reload. Accepted checks navigate to the saved report. History and the report identify connection checks separately from research actions; run completion does not establish provider success. Optional model usage details start collapsed, preserve provider/model/schema/output bounds and recorded calls, and label absent tokens or cost Unknown.

Loading and failed refreshes replace previous success status. Setup variable names and restart instructions stay behind collapsed Setup details, covering default OpenAI, trusted OPENAI_BASE_URL and explicit OpenRouter configuration. Costs and coverage limitations remain visible.

Connections verification uses mocked configured providers and submissions (no live calls), and covers explicit checks, consent reset, source selection, setup gating, idempotent recovery after lost responses, usage rendering, navigation and refresh without submissions, missing versus configured-but-untested setup, passed/failed attempt timestamps and safe text, saved research/discovery routing, configuration outage and retry, keyboard access, axe and 390px overflow. Capture desktop-connections.png and mobile-connections.png with the default collapsed setup disclosure; inspect status hierarchy, wrapping and focus visibility.
