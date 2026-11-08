"""Progress lines: what each tool call did, and the page's timeline with one entry per model step."""
from research_assistant.agents.progress import describe, timeline
from research_assistant.agents.tool_lines import Seen

AT = "2026-11-07T10:33:15+00:00"
APPLE = {"id": "company-0000320193", "kind": "company", "cik": "0000320193", "name": "Apple Inc.", "tickers": ["AAPL"]}
FACTS = {f"fact-{metric}": {"id": f"fact-{metric}", "kind": "fact", "cik": "0000320193", "metric": metric, "unit": "USD",
                            "value": value, "start": "2023-10-01", "end": "2024-09-28"}
         for metric, value in (("revenue", "391035000000"), ("gross_profit", "180683000000"))}
MARGIN = {"id": "calc-gm", "kind": "calc", "cik": "0000320193", "formula": "ratio", "value": "0.462063", "unit": "ratio",
          "inputs": {"numerator": "fact-gross_profit", "denominator": "fact-revenue"}, "start": "2023-10-01",
          "end": "2024-09-28", "status": "ok", "reason": None, "notes": []}
NO_PE = {**MARGIN, "id": "calc-pe", "formula": "pe", "value": None, "unit": "x", "inputs": {"price": "prices-a"},
         "start": None, "end": "2026-11-03", "status": "unavailable", "reason": "Earnings are negative, so no P/E."}


def call(name, arguments, data=None, status="ok", warnings=(), records=None, step=4, agent="fundamentals", **extra):
    return {"seq": extra.pop("seq", None), "at": AT, "kind": "tool_call", "agent": agent, "step": step, "name": name,
            "arguments": arguments, "repeat_of": None, "records": records or {},
            "result": {"status": status, "data": data, "ids": [], "source": "test", "warnings": list(warnings)}} | extra


def model(step, *names, agent="fundamentals", seq=None):
    return {"seq": seq, "at": AT, "kind": "model_call", "agent": agent, "step": step,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": "{}"}}
                           for i, n in enumerate(names)]}


LOOKUP = call("find_company", {"query": "AAPL"}, {"matches": [APPLE]}, records={APPLE["id"]: APPLE, **FACTS})


def lines(*events) -> list[str]:
    seen = Seen()
    return [describe(event, seen) for event in (LOOKUP, *events)][1:]


def test_each_tool_line_says_what_it_did_for_which_company_and_period():
    filing = {"id": "filing-0000320193-25-000001", "kind": "filing",
              "items": [{"code": "2.02", "name": "Results of operations and financial condition"}]}
    shown = lines(
        call("get_financials", {"cik": "320193", "metrics": ["revenue", "net_income"], "years": 2},
             {"cik": "0000320193", "fiscal_year_ends": ["2024-09-28", "2023-09-30"],
              "metrics": {"revenue": {"status": "ok"}, "net_income": {"status": "ok"}}}),
        call("calculate", {"formula": "ratio"}, MARGIN, records={MARGIN["id"]: MARGIN}),
        call("get_prices", {"ticker": "AAPL"},
             {"ticker": "AAPL", "start": "2025-11-03", "end": "2026-11-03", "trading_days": 251}),
        call("read_filing_section", {"cik": "320193", "item": "1A", "query": "supply chain"},
             {"filing": {"accession": "0000320193-24-000123", "form": "10-K", "filed": "2024-11-01"},
              "section": "part_i_item_1a", "total_chunks": 40, "chunks": [{}, {}], "query": "supply chain"}),
        call("read_filing_section", {"cik": "320193", "item": "2.02"},
             {"filing": {"accession": "0000320193-25-000001", "form": "8-K", "filed": "2025-01-30"},
              "section": "item_202", "total_chunks": 1, "chunks": [{}]}, records={filing["id"]: filing}),
        call("list_filings", {"cik": "320193", "forms": ["10-K", "4"], "since": "2025-01-01"},
             {"cik": "0000320193", "filings": [{}, {}, {}], "next_page": "2024-01-01/x"}),
        call("verify_against_filing", {"fact_id": "fact-revenue"}, {"fact_id": "fact-revenue", "verdict": "match"}),
        call("get_peers", {"cik": "320193"}, {"company": "Apple Inc.", "peers": [{"name": "Dell", "tickers": ["DELL"]}]}),
        call("get_macro", {}, {"as_of": "2026-11-05", "series": [{"name": "tbill_3m", "label": "3-month T-bill rate"}]}),
        call("get_insider_trades", {"cik": "320193"}, {"cik": "0000320193", "start": "2025-11-06", "end": "2026-11-06",
                                                      "filings_read": 54, "trades": [{}] * 48}),
        call("screen", {}, {"spec": {"filters": [{}], "rank_by": "net_margin"}, "counts": {"screened": 5, "returned": 4}},
             step=None, agent="host"),
        call("ask_market", {"task": "Price AAPL."}, {"status": "finished", "findings": [{}] * 3, "gaps": ["No 10-Q."]},
             agent="coordinator"))
    assert shown == [
        "[fundamentals] step 4: Reported figures: revenue, net income for AAPL, 2 years → OK, 2 fiscal years to 2024-09-28",
        "[fundamentals] step 4: Calculation: Gross margin, AAPL, year ended 2024-09-28 → OK, 46.2%",
        "[fundamentals] step 4: Prices: AAPL, 2025-11-03 to 2026-11-03 → OK, 251 trading days",
        '[fundamentals] step 4: Filing section: Item 1A Risk factors, AAPL 10-K 2024, search "supply chain" '
        "→ OK, 2 of 40 paragraphs",
        "[fundamentals] step 4: Filing section: Item 2.02 Results of operations and financial condition, AAPL 8-K 2025 "
        "→ OK, 1 of 1 paragraph",
        "[fundamentals] step 4: Filing list: 10-K, Form 4 for AAPL since 2025-01-01 → OK, 3 filings, more to page through",
        "[fundamentals] step 4: Check against the filing: Revenue, AAPL, year ended 2024-09-28 → OK, matches the filing",
        "[fundamentals] step 4: Peers: Apple Inc. → OK, 1 peer (DELL)",
        "[fundamentals] step 4: Economic data: 3-month T-bill rate → OK, as of 2026-11-05",
        "[fundamentals] step 4: Insider trades: AAPL, 2025-11-06 to 2026-11-06 → OK, 48 trades from 54 filings",
        "[host] Screen: 5 companies, 1 filter, ranked by net margin → OK, 4 candidates",
        "[coordinator] step 4: Market analyst → OK, 3 findings, 1 gap"]


def test_a_failed_call_shows_its_reason_and_not_its_arguments():
    junk = ">2025-11-03</parameter_name></invoke>" * 50
    partial = {"cik": "0000320193", "fiscal_year_ends": ["2024-09-28"],
               "metrics": {"revenue": {"status": "ok"}, "gross_profit": {"status": "not_found"}}}
    shown = lines(call("get_prices", {"ticker": "AAPL", "start": junk}, status="invalid",
                       warnings=["start: Input should be a valid date or datetime"]),
                  call("calculate", {"formula": "pe"}, NO_PE, status="unsupported", warnings=[NO_PE["reason"]]),
                  call("get_financials", {"cik": "320193"}, partial, status="partial", warnings=["revenue: restated."]),
                  call("read_filing_section", {"cik": "320193", "item": "9"}, status="not_found",
                       warnings=["No Item 9 in this 10-K."]))
    assert shown == [
        "[fundamentals] step 4: Prices → invalid: start: Input should be a valid date or datetime",
        "[fundamentals] step 4: Calculation: P/E, AAPL, at 2026-11-03 → unsupported: Earnings are negative, so no P/E.",
        "[fundamentals] step 4: Reported figures: the main figures for AAPL → partial, 1 fiscal year to 2024-09-28; "
        "none for gross profit",
        "[fundamentals] step 4: Filing section → not found: No Item 9 in this 10-K."]
    assert junk not in "".join(shown)


def test_a_model_step_is_one_entry_that_sums_up_its_calls():
    margins = [call("calculate", {}, MARGIN, seq=10 + i) for i in range(9)]
    entries = timeline([LOOKUP, model(4, *["calculate"] * 10, seq=9), *margins,
                        call("calculate", {}, NO_PE, status="unsupported", warnings=[NO_PE["reason"]]),
                        model(5, "calculate", "calculate"), call("calculate", {}, MARGIN, step=5),
                        call("calculate", {}, MARGIN, step=5, repeat_of=5)])
    [step4, step5] = [e for e in entries if e["kind"] == "model_call"]
    assert step4["text"] == "Step 4 · 10 calculations · 9 OK, 1 unsupported" and step4["at"] == AT
    assert step4["details"][0] == {"seq": 10, "text": "Calculation: Gross margin, AAPL, year ended 2024-09-28 → OK, 46.2%",
                                   "status": "ok"}
    assert step4["details"][-1]["text"].endswith("→ unsupported: Earnings are negative, so no P/E.")
    assert step5["text"] == "Step 5 · 2 calculations · 1 OK, 1 repeated"
    assert step5["details"][1]["text"].endswith("→ OK, 46.2% (repeat)") and step5["details"][1]["status"] == "repeat"
    # Only the lookup, which no model step asked for, stands alone; every other call sits under its step.
    assert [e["text"] for e in entries if e["kind"] == "tool_call"] == ['Company lookup: "AAPL" → OK, Apple Inc. (AAPL)']
    assert describe(model(4, *["calculate"] * 10)) == "[fundamentals] step 4: asked for 10 calculations"
    assert describe(model(6, "submit_findings")) == "[fundamentals] step 6: handing in findings"


def test_an_analysts_answer_folds_back_under_the_coordinators_step():
    ask = model(3, "ask_market", agent="coordinator")
    work = [{"at": AT, "kind": "analyst_start", "agent": "market", "task": "Price AAPL.", "follow_up": False},
            model(1, "get_prices", "submit_findings", agent="market"),
            call("get_prices", {}, {"ticker": "AAPL", "trading_days": 251}, step=1, agent="market"),
            {"at": AT, "kind": "finish", "agent": "market", "step": 1, "valid": False, "problems": ["findings: required"]}]
    working = timeline([ask, *work])
    assert working[0]["text"] == "Step 3 · market analyst · 1 with no result yet"
    assert working[2]["text"] == "Step 1 · price history, handing in findings · 1 OK, 1 invalid" and len(working[2]["details"]) == 2
    assert working[2]["details"][1] == {"seq": None, "status": "invalid",
                                        "text": "Handing in the answer → invalid: findings: required"}
    answered = call("ask_market", {}, {"status": "finished", "findings": [{}], "gaps": []}, step=3, agent="coordinator")
    done = timeline([ask, *work, {"at": AT, "kind": "analyst_end", "agent": "market", "status": "finished", "findings": 1},
                     answered])
    assert [(e["role"], e["text"]) for e in done] == [
        ("coordinator", "Step 3 · market analyst · OK"), ("market", "task: Price AAPL."),
        ("market", "Step 1 · price history, handing in findings · 1 OK, 1 invalid"), ("market", "done (finished): 1 findings")]
    assert done[0]["details"][0]["text"] == "Market analyst → OK, 1 finding, 0 gaps"


def test_calls_the_run_never_reached_say_not_run():
    entries = timeline([model(2, "calculate", "calculate"), call("calculate", {}, MARGIN, step=2),
                        {"kind": "run_end", "status": "failed"}])
    assert entries[0]["text"] == "Step 2 · 2 calculations · 1 OK, 1 not run"


def test_an_old_trace_still_renders():
    # Before records were frozen and roles tagged; this analyst_start predates follow_up.
    old = [{"seq": 1, "kind": "plan"}, {"seq": 2, "kind": "model_call", "step": 1, "tool_calls": [
               {"function": {"name": "find_company"}}, {"function": {"name": "calculate"}}]},
           {"seq": 3, "kind": "tool_call", "step": 1, "name": "find_company", "arguments": {"query": "AAPL"},
            "repeat_of": None, "result": {"status": "ok", "data": {"matches": [APPLE]}}},
           {"seq": 4, "kind": "tool_call", "step": 1, "name": "calculate", "arguments": {}, "repeat_of": None,
            "result": {"status": "ok", "data": MARGIN}},
           {"seq": 5, "kind": "analyst_start", "task": "Price AAPL."}]
    entries = timeline(old)
    assert [e["text"] for e in entries] == ["plan ready", "Step 1 · company lookup, calculation · all OK", "analyst_start"]
    assert [d["text"] for d in entries[1]["details"]] == [
        'Company lookup: "AAPL" → OK, Apple Inc. (AAPL)', "Calculation: Ratio, AAPL, year ended 2024-09-28 → OK, 46.2%"]
    assert entries[0] == {"seq": 1, "at": None, "kind": "plan", "role": None, "text": "plan ready"}
