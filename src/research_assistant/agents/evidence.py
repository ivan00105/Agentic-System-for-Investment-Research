"""Frozen evidence: a run's trace keeps every record its tools returned, in full (facts, filing paragraphs, the
daily prices behind a calculation), so a saved run can be reopened and its numbers rechecked offline, with no
SEC, price provider or model call. Files are enough for now; SQLite waits for the UI (PROJECT_GUIDE Phase 7)."""
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from pathlib import Path

from .. import config
from ..finance import quant, risk
from ..finance.filing_changes import measure_changes
from ..tools import calculate
from ..tools.result import ToolContext, ToolResult
from .checker import PLACEHOLDER, check, lookup
from .draft import SECTIONS, Draft


@dataclass
class SavedRun:
    events: list[dict]
    records: dict[str, dict]  # every record the run's tools returned, by ID (its latest version)
    # Each distinct version written under an ID, oldest first. Traces saved before price IDs covered their rows
    # (3 Nov 2026) can hold a refetched series twice under one ID, with float noise in Yahoo's adjusted closes.
    versions: dict[str, list[dict]]
    start: dict | None  # the run_start and run_end events, if the run got that far
    end: dict | None


@dataclass
class Recheck:
    calcs: int = 0  # calculations recomputed from their frozen inputs
    statements: int = 0  # report statements filled again from the frozen records
    problems: list[str] = field(default_factory=list)


def load(path: Path) -> SavedRun:
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    records: dict[str, dict] = {}
    versions: dict[str, list[dict]] = {}
    for event in events:
        for key, record in (event.get("records") or {}).items():
            records[key] = record
            if record not in versions.setdefault(key, []):
                versions[key].append(record)
    start = next((e for e in events if e["kind"] == "run_start"), None)
    end = next((e for e in reversed(events) if e["kind"] == "run_end"), None)
    return SavedRun(events, records, versions, start, end)


def recheck(path: Path) -> Recheck:
    """Recompute every calculation from the frozen records it cites and refill the final report's placeholders,
    then compare both with what the run saved. A mismatch is listed, never fixed."""
    run, outcome = load(path), Recheck()
    if not run.records:
        outcome.problems.append("The trace holds no tool records (it was saved before evidence was frozen), so "
                                "nothing could be rechecked.")
        return outcome
    cutoff = datetime.fromisoformat(run.start["cutoff"]) if run.start else datetime.now()
    for record in (r for versions in run.versions.values() for r in versions):
        if record.get("kind") != "calc":
            continue
        outcome.calcs += 1
        result = _recompute(record, run, cutoff)
        if result.status not in ("ok", "unsupported"):
            outcome.problems.append(f"{record['id']} could not be recomputed: {'; '.join(result.warnings)}")
        elif result.data["value"] != record["value"]:
            outcome.problems.append(f"{record['id']} ({record['formula']}) was saved as {record['value']} but "
                                    f"recomputes to {result.data['value']} from its frozen inputs.")
    if run.end and run.end.get("draft") is not None:
        report = check(Draft.model_validate(run.end["draft"]), run.records)
        saved = run.end["report"]["sections"]
        for key, _ in SECTIONS:
            if len(report.sections[key]) != len(saved[key]):
                outcome.problems.append(f"{key} has {len(report.sections[key])} statements in the saved draft but "
                                        f"{len(saved[key])} in the saved report.")
            for i, (claim, old) in enumerate(zip(report.sections[key], saved[key], strict=False)):
                outcome.statements += 1
                if claim.text != old["text"]:
                    outcome.problems.append(f"{key}[{i}] now reads {claim.text!r}, but the saved report has "
                                            f"{old['text']!r}.")
    return outcome


def _recompute(calc: dict, run: SavedRun, cutoff: datetime):
    """The calculation recomputed from the versions frozen under its input IDs, latest first. The first combination
    that gives the saved value wins; if none does, the latest versions' result is the one reported."""
    formula = calc.get("formula", "")
    if formula.startswith("outlook_"):
        return _recompute_outlook(calc, run)
    if formula in ("typical_results_day_move", "option_implied_range"):
        return _recompute_event_market_view(calc, run)
    if formula == "filing_change_alert":
        return _recompute_filing_change(calc, run)
    if formula not in calculate.ROLES:
        return ToolResult(status="unavailable", source="frozen calculations",
                          warnings=[f"No offline replay for {formula!r}."])
    ids = list(calc["inputs"].values())
    latest = None
    for chosen in product(*(run.versions.get(i, [])[::-1] or [None] for i in ids)):  # None: calculate says unknown
        records = {**run.records, **{i: r for i, r in zip(ids, chosen, strict=True) if r}}
        result = calculate.run(calculate.CalculateInput(formula=calc["formula"], inputs=calc["inputs"]),
                               ToolContext(cutoff=cutoff, sec=None, records=records))  # calculate never fetches
        latest = latest or result
        if result.status in ("ok", "unsupported") and result.data["value"] == calc["value"]:
            return result
    return latest


def _recompute_filing_change(calc: dict, run: SavedRun) -> ToolResult:
    source = "frozen filing text"
    inputs = calc.get("inputs") or {}
    method = calc.get("method")
    if method not in ("cosine", "tfidf"):
        return ToolResult(status="invalid", source=source, warnings=["Unknown frozen filing-change method."])
    sections = []
    for key in ("current_chunks", "prior_chunks"):
        ids = inputs.get(key)
        if not isinstance(ids, list) or not ids:
            return ToolResult(status="invalid", source=source, warnings=[f"No frozen {key} IDs."])
        paragraphs = []
        for chunk_id in ids:
            record = run.records.get(chunk_id, {}) if isinstance(chunk_id, str) else {}
            if record.get("kind") != "chunk" or not isinstance(record.get("text"), str):
                return ToolResult(status="invalid", source=source, warnings=[f"Missing frozen chunk {chunk_id}."])
            paragraphs.append(record["text"])
        sections.append("\n\n".join(paragraphs))
    similarity = measure_changes(sections[0], sections[1], method)["similarity"]
    return ToolResult(status="ok", data={"value": round(float(similarity), 8)}, ids=[calc["id"]], source=source)


def _recompute_event_market_view(calc: dict, run: SavedRun) -> ToolResult:
    """Recompute event-market-view calculations only from frozen price and observation inputs."""
    inputs = calc.get("inputs") or {}
    if calc.get("formula") == "option_implied_range":
        spot = inputs.get("spot")
        straddle = inputs.get("straddle")
        if not isinstance(spot, (int, float)) or not isinstance(straddle, (int, float)) or spot <= 0:
            return ToolResult(status="invalid", source="events",
                              warnings=["Frozen option-implied range inputs are incomplete."])
        value = round(straddle / spot, 8)
        return ToolResult(status="ok", data={"value": value}, ids=[calc["id"]], source="frozen events")
    prices = run.records.get(inputs.get("prices"))
    dates = inputs.get("earnings_dates") or []
    if not prices or not isinstance(dates, list):
        return ToolResult(status="invalid", source="events",
                          warnings=["Frozen results-day move inputs are incomplete."])
    rows = {row["date"]: row["adj_close"] for row in prices.get("rows", [])}
    ordered = sorted(rows)
    moves = []
    for filing_date in dates:
        index = next((i for i, day in enumerate(ordered) if day >= filing_date), None)
        if index is not None and index > 0:
            prior, current = ordered[index - 1], ordered[index]
            if rows[prior] != 0:
                moves.append(abs(rows[current] / rows[prior] - 1))
    if not moves:
        return ToolResult(status="unavailable", source="events",
                          warnings=["No frozen filing-day closes could be matched."])
    value = round(statistics.median(moves), 8)
    return ToolResult(status="ok", data={"value": value}, ids=[calc["id"]], source="frozen events")


def _recompute_outlook(calc: dict, run: SavedRun) -> ToolResult:
    """Recompute a get_outlook metric from the two frozen price series, without fetching prices."""
    inputs = calc.get("inputs") or {}
    stock = run.records.get(inputs.get("prices"))
    benchmark = run.records.get(inputs.get("benchmark"))
    horizon = inputs.get("horizon")
    if not stock or not benchmark or not isinstance(horizon, int):
        return ToolResult(status="invalid", source="outlook", warnings=["Frozen outlook inputs are incomplete."])
    stock_rows = {row["date"]: row["adj_close"] for row in stock.get("rows", [])}
    benchmark_rows = {row["date"]: row["adj_close"] for row in benchmark.get("rows", [])}
    allowed_dates = set(inputs.get("sessions", []))
    dates = sorted(stock_rows.keys() & benchmark_rows.keys() & allowed_dates) if allowed_dates else sorted(
        stock_rows.keys() & benchmark_rows.keys()
    )
    if str(calc.get("formula", "")).startswith("outlook_direction_"):
        outcome = quant.direction_forecast(
            [stock_rows[day] for day in dates],
            [benchmark_rows[day] for day in dates],
            horizon,
            min_observations=config.DIRECTION_MIN_OBSERVATIONS,
            regularization=config.DIRECTION_REGULARIZATION,
            learning_rate=config.DIRECTION_LEARNING_RATE,
            max_iterations=config.DIRECTION_MAX_ITERATIONS,
        )
        direction_metric = {
            "direction_probability": "probability",
            "direction_base_rate": "base_rate",
            "direction_observations": "observations",
            "direction_auc": "auc",
            "direction_brier_skill": "brier_skill",
        }.get(str(calc["formula"]).removeprefix("outlook_"))
        value = getattr(outcome.value, direction_metric, None) if outcome.value is not None else None
        data = {**calc, "value": round(value, 8) if value is not None else None,
                "status": "ok" if value is not None else "unsupported", "reason": outcome.reason}
        return ToolResult(status=data["status"], data=data, source="outlook",
                          warnings=[outcome.reason] if outcome.reason else [])
    outcome = risk.forecast(
        [stock_rows[day] for day in dates],
        [benchmark_rows[day] for day in dates],
        horizon,
        periods_per_year=config.TRADING_DAYS_PER_YEAR,
        quantile_low=config.OUTLOOK_QUANTILE_LOW,
        quantile_high=config.OUTLOOK_QUANTILE_HIGH,
        trailing_threshold=config.OUTLOOK_TRAILING_THRESHOLD,
        har_week_days=config.OUTLOOK_HAR_WEEK_DAYS,
        har_month_days=config.OUTLOOK_HAR_MONTH_DAYS,
        conformal_coverage=config.OUTLOOK_CONFORMAL_COVERAGE,
        conformal_learning_rate=config.OUTLOOK_CONFORMAL_LEARNING_RATE,
        min_observations=config.OUTLOOK_MIN_OBSERVATIONS,
        session_dates=dates,
        earnings_dates=set(inputs.get("earnings_dates", [])),
        earnings_in_window=bool(inputs.get("earnings_in_window", False)),
    )
    metric = {
        "own_return_low": "own_low",
        "own_return_high": "own_high",
        "relative_return_low": "relative_low",
        "relative_return_high": "relative_high",
        "trail_spy_probability": "trail_probability",
        "earnings_jump": "earnings_jump",
    }.get(str(calc["formula"]).removeprefix("outlook_"), str(calc["formula"]).removeprefix("outlook_"))
    value = getattr(outcome.value, metric, None) if outcome.value is not None else None
    data = {**calc, "value": round(value, 8) if value is not None else None,
            "status": "ok" if value is not None else "unsupported", "reason": outcome.reason}
    return ToolResult(status=data["status"], data=data, source="outlook", warnings=[outcome.reason] if outcome.reason else [])


def inject_wrong_period(draft: Draft, records: dict[str, dict]) -> tuple[Draft, str] | None:
    """A labelled test defect for the isolated review test (REFERENCE §7: wrong period). The first figure, key numbers
    first, whose metric has an earlier fiscal year in the frozen records is swapped for the latest earlier year the
    claim doesn't already use, while its words still name the later period. None if no figure qualifies."""
    for key in ["key_numbers"] + [key for key, _ in SECTIONS if key != "key_numbers"]:
        for i, claim in enumerate(getattr(draft, key)):
            used = {r["id"] for m in PLACEHOLDER.finditer(claim.text) if (r := lookup(records, m[2], m[1]))}
            used |= {c.strip() for c in claim.citations}
            for match in PLACEHOLDER.finditer(claim.text):
                fact = lookup(records, match[2], match[1])
                if not fact or fact.get("kind") != "fact":
                    continue
                earlier = [r for r in records.values() if r.get("kind") == "fact" and r["id"] not in used
                           and all(r.get(k) == fact.get(k) for k in ("cik", "metric", "unit"))
                           and bool(r.get("start")) == bool(fact.get("start")) and r["end"] < fact["end"]]
                if not earlier:
                    continue
                swap = max(earlier, key=lambda r: r["end"])
                text = claim.text[:match.start()] + "{fact:%s}" % swap["id"] + claim.text[match.end():]
                citations = [swap["id"] if c.strip() == fact["id"] else c for c in claim.citations]
                changed = draft.model_copy(deep=True)
                getattr(changed, key)[i] = claim.model_copy(update={"text": text, "citations": citations})
                return changed, (f"{key}[{i}]: {fact['id']} ({fact['metric']}, period ending {fact['end']}) was "
                                 f"replaced by {swap['id']} (period ending {swap['end']}); the words are unchanged.")
    return None
