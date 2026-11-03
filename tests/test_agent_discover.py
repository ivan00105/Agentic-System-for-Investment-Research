import json
from datetime import datetime, timezone

import httpx
import openai
import pandas as pd
import pytest
from fake_llm import FakeClient, reply, resubmit
from sec_files import make_context

from research_assistant.agents import discover, single_agent
from research_assistant.agents.acceptance import Acceptance
from research_assistant.agents.discover_spec import PriceCheck
from research_assistant.agents.trace import Trace
from research_assistant.data import prices_yfinance, universe
from research_assistant.model_access import ModelSettings
from research_assistant.tools.result import ToolResult
from research_assistant.tools.screen import Filter

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")
CUTOFF = datetime(2025, 6, 1, tzinfo=timezone.utc)  # the screen's latest complete year is 2024, as in the fixtures
ERROR = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
MEMBERS = {"AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810", "GOOGL": "0001652044",
           "GOOG": "0001652044", "JPM": "0000019617"}
LARGE = {"term": "large", "definition": "revenue of at least $10 billion", "question": "What revenue counts as large?"}


@pytest.fixture
def declared(tmp_path):
    path = tmp_path / "five.yaml"
    path.write_text("name: Five test companies\nsource: tests\nas_of: 2025-06-01\nnote: A test list.\ncompanies:\n"
                    + "".join(f'  - {{ticker: "{t}", cik: "{c}", name: "{t} Inc."}}\n' for t, c in MEMBERS.items()),
                    encoding="utf-8")
    return universe.load(str(path))


def spec(**fields):
    return reply(tool_calls=[("submit_screen_spec", {"rank_by": "operating_margin", **fields})])


def research(ticker: str, cik: str):
    report = {"summary": [{"text": f"{ticker} files annual reports with the SEC.", "citations": [f"company-{cik}"]}]}
    return [reply("1. find_company"), reply(tool_calls=[("find_company", {"query": ticker})]),
            reply(tool_calls=[("submit_report", report)]), resubmit]


def find(tmp_path, declared, *script, **options):
    client = FakeClient(*script)
    result = discover.run("Find large tech companies with operating margin above 25%.", client, SETTINGS,
                          make_context(tmp_path, cutoff=CUTOFF), declared, research=single_agent.run,
                          condition=single_agent.CONDITION, trace_dir=tmp_path / "traces", **options)
    events = [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]
    return result, client, events


def test_candidates_failing_the_10k_check_are_replaced_and_the_pick_is_researched(tmp_path, declared):
    asked = []
    result, client, events = find(
        tmp_path, declared,
        spec(filters=[{"metric": "operating_margin", "op": ">", "value": 0.25}], top_k=1, terms=[LARGE]),
        *research("AAPL", "0000320193"), ask=lambda term: asked.append(term.term) or "")
    assert result.status == "finished" and asked == ["large"]
    assert result.counts == {"screened": 5, "eligible": 4, "ranked": 4, "checked": 4, "rejected": 3,
                             "researched": 1, "failed": 0, "replaced": 3, "returned": 1}
    outcomes = [(c.cik, c.outcome) for c in result.candidates]
    assert outcomes == [("0001045810", "rejected"), ("0000789019", "rejected"), ("0001652044", "rejected"),
                        ("0000320193", "picked")]
    apple = result.candidates[3]
    assert apple.verdict.state == "pass" and apple.verdict.lines[0].text.startswith("operating margin > 25.0%: 31.5%")
    assert "unknown" in result.candidates[0].verdict.lines[0].text  # no companyfacts for NVIDIA in the fixtures
    # The research run is a normal condition B run with its own trace; the Discover totals include it.
    research_end = next(e for e in events if e["kind"] == "research_end")
    assert research_end["status"] == "finished" and research_end["trace"] != str(result.trace_path)
    assert result.totals["model_calls"] == 1 + apple.run.totals["model_calls"]
    brief = client.requests[1]["messages"][1]["content"]
    assert "Apple Inc. (AAPL, CIK 0000320193)" in brief and "operating margin > 25.0%" in brief
    assert "- large: revenue of at least $10 billion" in brief
    assert "It is shortlist pick 1 of the 1 asked for." in brief and "ranked it 4 by operating margin" in brief
    assert "The 3 ranked above it that aren't picked failed the host's check" in brief
    shown = next(e for e in events if e["kind"] == "screen_spec")["shown"]
    assert '"large" read as: revenue of at least $10 billion (proposed and accepted by the user)' in shown
    assert next(e for e in events if e["kind"] == "run_end")["counts"] == result.counts
    md = result.markdown
    assert "## Shortlist" in md and "### 1. Apple Inc. (AAPL, CIK 0000320193)" in md
    assert "| 5 | 4 | 4 | 4 | 3 | 1 | 0 | 3 | 1 |" in md and "AAPL files annual reports with the SEC." in md
    assert "## Research report 1: Apple Inc." in md and "### NVIDIA CORP (NVDA, CIK 0001045810): rejected" in md
    # The host's tool calls are traced with their records, so the checks are frozen evidence too.
    host = [e for e in events if e["kind"] == "tool_call" and e.get("agent") == "host"]
    assert host[0]["name"] == "screen" and host[0]["arguments"]["universe"] == declared.ciks
    assert any(e["records"] for e in host if e["name"] == "calculate")


def test_a_failed_research_run_is_replaced_by_the_next_candidate(tmp_path, declared):
    result, _, _ = find(tmp_path, declared,
                        spec(rank_by="revenue", filters=[{"metric": "revenue", "op": ">", "value": 0}], top_k=1),
                        ERROR, *research("JPM", "0000019617"))
    outcomes = [(c.cik, c.outcome) for c in result.candidates if c.outcome != "not reached"]
    assert outcomes == [("0000320193", "research failed"), ("0001652044", "rejected"), ("0000789019", "rejected"),
                        ("0000019617", "picked")]
    assert result.counts["failed"] == 1 and result.counts["researched"] == 2 and result.counts["returned"] == 1


def test_a_research_run_that_crashes_is_replaced_not_fatal(tmp_path, declared):
    calls = []

    def crash_first(question, *args, **kwargs):
        calls.append(question)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return single_agent.run(question, *args, **kwargs)

    client = FakeClient(spec(rank_by="revenue", filters=[{"metric": "revenue", "op": ">", "value": 0}], top_k=1),
                        *research("JPM", "0000019617"))
    result = discover.run("Find big companies.", client, SETTINGS, make_context(tmp_path, cutoff=CUTOFF), declared,
                          research=crash_first, condition="B", trace_dir=tmp_path / "traces")
    apple = result.candidates[0]
    assert apple.outcome == "research failed" and "RuntimeError: boom" in apple.error
    assert result.counts["researched"] == 2 and result.counts["returned"] == 1
    assert "- Research: The research run crashed (RuntimeError: boom). This is a bug." in result.markdown


def test_the_research_limit_returns_fewer_and_says_why(tmp_path, declared):
    result, _, _ = find(tmp_path, declared,
                        spec(rank_by="revenue", filters=[{"metric": "revenue", "op": ">", "value": 0}], top_k=1),
                        ERROR, replacements=0)
    assert result.counts["researched"] == 1 and result.counts["returned"] == 0
    assert any(n.startswith("Stopped at the research limit: 1 research runs") for n in result.notes)
    assert "No candidate passed." in result.markdown


def test_an_answer_revises_the_spec_and_unasked_terms_stay_assumed(tmp_path, declared):
    cheap = {"term": "cheap", "definition": "P/E below 20", "question": "What P/E is cheap?"}
    revised = spec(filters=[{"metric": "operating_margin", "op": ">", "value": 5}],
                   price_checks=[{"metric": "pe", "op": "<", "value": 15}],
                   terms=[cheap | {"definition": "P/E below 15"}, LARGE])
    answers = {"cheap": "P/E below 15", "large": None}
    result, client, events = find(tmp_path, declared, spec(terms=[cheap, LARGE]), revised,
                                  ask=lambda term: answers[term.term])
    assert result.interpretation.sources == {"cheap": "user", "large": "assumed"}
    assert "- cheap: P/E below 15" in client.requests[1]["messages"][-1]["content"]
    assert [e["answer"] for e in events if e["kind"] == "clarify"] == ["P/E below 15", None]
    assert result.counts["eligible"] == 0 and result.counts["returned"] == 0
    assert any(n.startswith("Every ranked candidate was checked: 0 of the 3") for n in result.notes)
    assert '"large" read as: revenue of at least $10 billion (assumed: not confirmed by the user)' in result.markdown


def test_a_term_the_user_defined_up_front_is_not_asked(tmp_path, declared):
    valuation = {"term": "reasonable valuation", "definition": "P/E below 40", "question": "What P/E?"}
    result, client, events = find(tmp_path, declared, spec(filters=[{"metric": "operating_margin", "op": ">", "value": 5}],
                                                          terms=[valuation]),
                                  ask=lambda term: pytest.fail("asked"), defined={"reasonable valuation": "P/E below 40"})
    assert "The user defined these terms:\n- reasonable valuation: P/E below 40" in client.requests[0]["messages"][1]["content"]
    assert result.interpretation.sources == {"reasonable valuation": "user"}
    assert not [e for e in events if e["kind"] == "clarify"]


def test_no_spec_means_a_failed_run_with_a_trace(tmp_path, declared):
    result, _, events = find(tmp_path, declared, ERROR)
    assert result.status == "failed" and result.counts == {}
    assert "- Run status: failed" in result.markdown and events[-1]["kind"] == "run_end"


def test_a_failed_screen_ends_the_run_and_still_shows_the_spec(tmp_path, declared, monkeypatch):
    monkeypatch.setattr(discover.Acceptance, "call", lambda self, name, args: ToolResult(
        status="unavailable", source="SEC frames", warnings=["SEC is down."]))
    result, _, _ = find(tmp_path, declared, spec(top_k=2))
    assert result.status == "failed" and result.error == "The screen came back unavailable: SEC is down."
    assert "; top 2." in result.markdown


def test_price_checks_use_the_latest_close_and_10k(tmp_path, monkeypatch):
    days = pd.to_datetime(["2025-05-28", "2025-05-29", "2025-05-30"])
    frame = pd.DataFrame({"Close": [200.0, 201.0, 202.0], "Adj Close": [200.0, 201.0, 202.0], "Volume": [1.0] * 3,
                          "Dividends": [0.0] * 3, "Stock Splits": [0.0] * 3}, index=days)
    monkeypatch.setattr(prices_yfinance, "_history", lambda ticker, start, end: (frame, pd.Series(dtype=float)))
    context = make_context(tmp_path, cutoff=CUTOFF)
    host = Acceptance(context, Trace.new(tmp_path / "traces"))
    verdict = host.check("0000320193", ["AAPL"], [Filter(metric="revenue_growth", op=">", value=0),
                                                  PriceCheck(metric="pe", op="<", value=20)])
    growth, pe = verdict.lines
    assert growth.state == "pass" and growth.text.startswith(
        "revenue growth > 0.0%: 2.0% (fiscal year ending 2024-09-28 against the one before)")
    assert pe.state == "fail" and pe.text.startswith("pe < 20.0x: ") and verdict.state == "fail"
    record = context.records[pe.ids[0]]
    assert record["formula"] == "pe" and context.records[record["inputs"]["market_cap"]]["formula"] == "market_cap"


def test_the_bundled_universe_is_declared_with_its_source():
    sp500 = universe.load("sp500_tech")
    assert len(sp500.members) == 97 and len(sp500.ciks) == 94  # GOOG/GOOGL, FOX/FOXA, NWS/NWSA
    assert all(isinstance(m.ticker, str) for m in sp500.members) and "ON" in {m.ticker for m in sp500.members}
    assert sp500.as_of == "2026-11-03" and "wikipedia" in sp500.source


def test_a_bad_universe_says_what_to_fix(tmp_path):
    with pytest.raises(universe.UniverseError, match="sp500_tech"):
        universe.load("nope")
    (tmp_path / "bad.yaml").write_text("name: x\n", encoding="utf-8")
    with pytest.raises(universe.UniverseError, match="needs name, source, as_of and companies"):
        universe.load(str(tmp_path / "bad.yaml"))
