# Fieldnote UI contract

Purpose: inspect a stock-research result, its source evidence, and the change caused by review. Audience: a course demonstrator and an evaluator who needs to distinguish a supported calculation from a persuasive narrative.

Primary action: open a saved teaching example or explicitly submit a new investigation. The first screen is the application. Hierarchy: controls → run mode and cutoff → report → claim/source link → correction → separate forecast → limitations → activity log.

Visual direction: compact editorial research desk, warm neutral surfaces, forest-green actions, amber qualifications, aligned numerical columns and restrained typography. A source desk beside the report is the memorable interaction. Local product requirements establish these choices; no external design service or assets are used.

Target viewports: 1440x900 and 390x844. On narrow screens the source desk is an inline section. Citation activation focuses the source heading; closing returns focus to the triggering citation. Tables scroll inside their own region. Long source IDs wrap. Controls use visible focus and text labels; status does not rely on colour. Reduced motion removes progress animation.

Content states:

| State | Trigger | Feedback and safe next action |
|---|---|---|
| Loading | Run/source/history fetch pending | Named loading message; no invented progress percentage |
| Empty | Research opened without a run | Explain first action and offer labelled teaching example |
| Error | Missing ID, configuration or network | Specific message; retry connection or choose new input; no automatic paid retry |
| Partial | Facts saved but inference fails | Financial report preserved with failure and model-review limitation |
| Success | Stored result available | Completed operational state, separate qualified report, citations and history |
| Permission | Cross-site access blocked | API returns an explicit local-only 403; no login/permission UI exists in this single-user milestone |

Verification: browser screenshots, accessible names, keyboard skip/focus, axe checks, no document horizontal overflow, long-content injection fixture, reduced motion, reconnect and idempotency tests. The bundled frontend skill checker validates the evidence record; it does not replace visual inspection.
