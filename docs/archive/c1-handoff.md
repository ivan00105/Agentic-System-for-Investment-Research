# C1 — SEC filing evidence and financial records

**Implementation complete, 31 October 2026; maintenance only.** Tasks 3.2, 4.1 and 4.2 are done, and the 3.1 packet is prepared. The remaining independent packet review and C0 acceptance are [separate outstanding items](../STATUS.md#remaining-c1-acceptance). No new C1 feature task is needed unless review finds a concrete defect.

Assignment: tasks **3.2, 4.1 and 4.2**, following the [3.1 MSFT FY2024 packet](../verification/packets/msft-fy2024/20261029T182734Z/README.md).
Base commit: `2c7f20378ae0667d9d3336758854234e9cacf211`.
Changes are uncommitted. Existing packet bytes, live stores, credentials and running servers were preserved.

## Delivered behavior

- Fresh research selects eligible annual company-facts rows, retrieves that exact
  accession's SEC index and primary filing, and checks issuer, form, period,
  amendment, units and undimensioned annual context. Failed archival retrieval or
  conflicting values does not silently fall back to aggregate metrics.
  The single retrieval worker paces SEC requests below ten per second; a fresh
  company reserves three source operations against the existing tool budget.
- Evidence distinguishes `companyfacts` from `filing_table`. The filing packet
  retains accession, CIK, filing/report dates, recorded acceptance when present,
  URL, UTC retrieval time, byte length and SHA-256 for the index, primary document
  and extracted table. The full received filing is preserved, including delivery
  additions. Table and fact locators refer to those exact received bytes.
- Typed facts retain display/normalized values, scale/precision, USD unit,
  concept, duration, issuer, basis/scope, accession, evidence and snapshot.
  Unknown basis/scope stays explicit and cannot supply a validated metric.
- `operating-margin-v1` stores immutable input fact IDs, precision 28,
  ROUND_HALF_EVEN, and either the Decimal result or a typed missing, invalid,
  incompatible or nonpositive-revenue failure. Metrics reference facts and the
  saved calculation. Existing input IDs cannot be rewritten in place.
- Frozen and replay runs preserve facts, calculation records and source hashes;
  they do not retrieve newer filings or recalculate from newer inputs. Packet
  source hashes/sizes are checked when evidence is saved or copied.

## Interfaces and compatibility

`Evidence` adds `source_kind` and optional `packet`; old records default to
`legacy`. `CompanyReport` adds default-empty `facts` and `calculations`.
`Metric` adds optional `fact_id` and `calculation_id`. Existing fields, metric
names and fixture behavior remain available. The existing evidence endpoint now
returns these additive fields.

`GET /api/runs/{run_id}/evidence/{evidence_id}/sources/{digest}` returns exact
saved bytes only for that evidence's own snapshot or packet documents. It uses
attachment disposition and `application/octet-stream`; archived HTML is not
rendered as application content. No arbitrary path or URL can be requested.

SQLite initialization adds `financial_facts` and `calculations` tables. It does
not backfill or rewrite historical reports. Financial records and their report
update commit together; invalid references or changed contents roll back.
Legacy frozen reports preserve legacy numbers without claiming new typed
validation. Existing synthetic examples remain labelled synthetic.

For deployment, follow the existing stopped-server whole-data backup procedure.
An old application build cannot be assumed to read new record fields; rollback
uses its pre-upgrade data backup. Do not strip or rewrite saved report JSON.

## Verification and limits

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

Focused cases use synthetic transports and the preserved public MSFT packet:
identity/accession/date/cutoff and link boundaries; failures/oversize responses;
raw-byte integrity and scoped download; units/durations/scope and conflicting
tags; known margin and Decimal-context isolation; missing/zero/negative inputs;
immutable persistence, database reopen, and frozen/replay with network forbidden.
These are software and saved-source checks, not a new live-provider experiment.

Recorded checks: **195 backend tests passed** (one existing upstream
Starlette/httpx deprecation warning); **frontend production build passed**;
the original sealed packet's offline verifier and **12 mismatch cases passed**.
[Runtime evidence](../verification/c1-runtime.json) retains a complete saved-source
MSFT FY2024 report, typed fact/calculation IDs, evidence records and isolated-store
location. It reproduces the checked **44.6443%** margin without a live provider call.

Coverage remains narrow: supported US-GAAP revenue tags and OperatingIncomeLoss,
annual undimensioned USD contexts, and the documented numeric transforms in
`financials.py`. Unsupported filings fail explicitly. General XBRL, other
currencies, quarterly calculations, claim correction and company-directory work
are outside C1. The 2026 company-facts snapshot is not a reconstructed 2024 API
vintage. Separate-person review of task 3.1 and C0 integration acceptance remain
pending. C6 owns richer presentation of the new records.
