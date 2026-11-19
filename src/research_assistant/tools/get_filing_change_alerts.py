"""Host-owned filing-change alerts from current and prior 10-K sections."""

from pydantic import BaseModel, Field

from .. import config
from ..data import sec_filings, sec_sections
from ..data.errors import DataError
from ..data.sec import cik10
from ..finance.filing_changes import measure_changes
from .result import Tool, ToolContext, ToolResult, make_id


class GetFilingChangeAlertsInput(BaseModel):
    cik: str = Field(pattern=r"^[0-9]{1,10}$", description="The company's CIK from find_company.")
    accession: str | None = Field(
        None,
        pattern=r"^\d{10}-\d{2}-\d{6}$",
        description="Optional current 10-K accession; otherwise use the latest 10-K before the cutoff.",
    )
    items: list[str] | None = Field(
        None,
        description='Sections to compare; defaults to ["1A", "7"]. Only 1A and 7 are supported.',
    )
    method: str = Field("tfidf", description='Deterministic text method: "tfidf" or "cosine".')


def _annual_pair(context: ToolContext, cik: str, accession: str | None):
    if accession:
        current = sec_filings.find(context.sec, cik, accession)
        if current is None:
            return None, None, f"No filing {accession} for CIK {cik}."
        if current.form != "10-K":
            return None, None, f"{accession} is {current.form}, not a 10-K."
        if not current.public_by(context.cutoff):
            return None, None, f"{accession} was filed after the cutoff."
    else:
        latest = sec_filings.search(context.sec, cik, context.cutoff, forms={"10-K"}, limit=1)
        if not latest:
            return None, None, "No 10-K before the cutoff."
        current = latest[0]

    candidates = sec_filings.search(context.sec, cik, context.cutoff, forms={"10-K"})
    prior = next((filing for filing in candidates
                  if (filing.filed, filing.accession) < (current.filed, current.accession)), None)
    if prior is None:
        return current, None, "No prior 10-K before the current filing."
    return current, prior, None


def _section(found: dict, item: str) -> tuple[str | None, dict | None]:
    names = sec_sections.find_item(found, item, None)
    if len(names) != 1:
        return None, None
    name = names[0]
    return name, found[name]


def run(args: GetFilingChangeAlertsInput, context: ToolContext) -> ToolResult:
    cik = cik10(args.cik)
    items = list(dict.fromkeys(args.items or list(config.FILING_CHANGE_DEFAULT_ITEMS)))
    invalid = sorted(set(items) - {"1A", "7"})
    if invalid:
        return ToolResult(status="invalid", source="SEC filing text", warnings=[
            f"Unsupported filing section {invalid[0]}; use Item 1A or Item 7."
        ])
    if args.method not in {"tfidf", "cosine"}:
        return ToolResult(status="invalid", source="SEC filing text",
                          warnings=['method must be "tfidf" or "cosine".'])

    try:
        current, prior, problem = _annual_pair(context, cik, args.accession)
    except DataError as exc:
        return ToolResult(status="unavailable", source="SEC filing text", warnings=[str(exc)])
    except Exception as exc:
        return ToolResult(status="unavailable", source="SEC filing text",
                          warnings=[f"Could not list SEC filings: {exc}"])
    if problem:
        status = "not_found" if "No filing" in problem or "No prior" in problem or "No 10-K" in problem else "invalid"
        return ToolResult(status=status, source="SEC filing text", warnings=[problem])

    warnings = []
    records = []
    for item in items:
        try:
            current_found = sec_sections.sections(context.sec, current, context.cache("section_cache"))
            prior_found = sec_sections.sections(context.sec, prior, context.cache("section_cache"))
        except DataError as exc:
            warnings.append(f"Item {item} unavailable: {exc}")
            continue
        except Exception as exc:
            warnings.append(f"Item {item} unavailable: {exc}")
            continue

        current_name, current_section = _section(current_found, item)
        prior_name, prior_section = _section(prior_found, item)
        if current_section is None or prior_section is None:
            missing = "current" if current_section is None else "prior"
            warnings.append(f"Item {item} unavailable: no unambiguous section in the {missing} 10-K.")
            continue

        text_current = current_section["text"]
        text_prior = prior_section["text"]
        if not text_current.strip() or not text_prior.strip():
            warnings.append(f"Item {item} unavailable: its text is empty in one 10-K.")
            continue

        chunks_current = sec_sections.chunks(text_current)
        chunks_prior = sec_sections.chunks(text_prior)
        current_chunk_ids = []
        prior_chunk_ids = []
        for n, paragraph in enumerate(chunks_current):
            record = {
                "id": f"chunk-{current.accession}-{current_name}-{n}",
                "kind": "chunk",
                "cik": cik,
                "accession": current.accession,
                "form": current.form,
                "section": current_name,
                "n": n,
                "text": paragraph,
                "url": current.url,
            }
            context.remember(record)
            current_chunk_ids.append(record["id"])
        for n, paragraph in enumerate(chunks_prior):
            record = {
                "id": f"chunk-{prior.accession}-{prior_name}-{n}",
                "kind": "chunk",
                "cik": cik,
                "accession": prior.accession,
                "form": prior.form,
                "section": prior_name,
                "n": n,
                "text": paragraph,
                "url": prior.url,
            }
            context.remember(record)
            prior_chunk_ids.append(record["id"])

        values = measure_changes(text_current, text_prior, args.method)
        prefix = make_id(
            "filing-change",
            cik,
            current.accession,
            prior.accession,
            item,
            args.method,
        )
        record = {
            "id": prefix,
            "kind": "calc",
            "formula": "filing_change_alert",
            "ticker": None,
            "cik": cik,
            "item": item,
            "method": args.method,
            "value": round(float(values["similarity"]), 8),
            "unit": "similarity",
            "similarity": round(float(values["similarity"]), 8),
            "issued_at": context.cutoff.isoformat(),
            "start": prior.report_date.isoformat() if prior.report_date else prior.filed.isoformat(),
            "end": current.report_date.isoformat() if current.report_date else current.filed.isoformat(),
            "inputs": {
                "current_accession": current.accession,
                "prior_accession": prior.accession,
                "current_chunks": current_chunk_ids,
                "prior_chunks": prior_chunk_ids,
            },
            "new_text_share": round(float(values["new_text_share"]), 8),
            "status": "ok",
            "notes": [
                f"Deterministic {args.method} cosine comparison of complete Item {item} text.",
                "No LLM calculation was used.",
            ],
        }
        context.remember(record)
        records.append(record)

    if not records:
        return ToolResult(status="unavailable", source="SEC filing text",
                          warnings=warnings or ["No filing-change record could be calculated."])
    status = "partial" if len(records) != len(items) or warnings else "ok"
    data = {
        "cik": cik,
        "current": {
            "accession": current.accession,
            "filed": current.filed.isoformat(),
            "url": current.url,
        },
        "prior": {
            "accession": prior.accession,
            "filed": prior.filed.isoformat(),
            "url": prior.url,
        },
        "alerts": [
            {
                "id": record["id"],
                "item": record["item"],
                "method": record["method"],
                "similarity": record["value"],
                "new_text_share": record["new_text_share"],
                "current_chunks": record["inputs"]["current_chunks"],
                "prior_chunks": record["inputs"]["prior_chunks"],
            }
            for record in records
        ],
    }
    return ToolResult(status=status, data=data, ids=[record["id"] for record in records],
                      source="SEC EDGAR filing text", warnings=warnings)


TOOL = Tool(
    "get_filing_change_alerts",
    "Compare Item 1A and Item 7 text in the latest 10-K against the prior 10-K using deterministic "
    "TF-IDF or cosine similarity. Returns frozen citable calc records; it uses no LLM for the number.",
    GetFilingChangeAlertsInput,
    run,
    "SEC EDGAR filing text",
)
