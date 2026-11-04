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


def test_research_runs_with_no_claims_count_as_failed(tmp_path, declared):
    # Codex review: a run that stopped at its limit with no claims, or abstained in every section, was a pick.
    def short(question, *args, **kwargs):
        return single_agent.run(question, *args, max_steps=1, **kwargs)

    stopped = [reply("1. find_company"), reply(tool_calls=[("find_company", {"query": "AAPL"})]),
               reply(tool_calls=[("submit_report", {"limitations": ["Ran out of steps."]})])]
    abstained = [reply("1. say so"), reply(tool_calls=[("submit_report", {"limitations": ["Nothing found."]})])]
    client = FakeClient(spec(rank_by="revenue", filters=[{"metric": "revenue", "op": ">", "value": 0}], top_k=1),
                        *stopped, *abstained)
    result = discover.run("Find big companies.", client, SETTINGS, make_context(tmp_path, cutoff=CUTOFF), declared,
                          research=short, condition="B", trace_dir=tmp_path / "traces")
    apple, jpm = (next(c for c in result.candidates if c.cik == cik) for cik in ("0000320193", "0000019617"))
    assert (apple.outcome, apple.run.status) == ("research failed", "stopped_at_limit")
    assert apple.error == "The research run stopped at its step limit with no claims."
    assert (jpm.outcome, jpm.run.status) == ("research failed", "finished")
    assert jpm.error == "The research run abstained in every section."
    assert result.counts["failed"] == 2 and result.counts["returned"] == 0
    events = [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]
    assert [e["error"] for e in events if e["kind"] == "research_end"] == [apple.error, jpm.error]


def test_a_spec_edited_directly_is_used_as_it_is_without_a_model_call(tmp_path, declared):
    cheap = {"term": "cheap", "definition": "P/E below 20", "question": "What P/E is cheap?"}
    draft = {"rank_by": "operating_margin", "terms": [cheap, LARGE]}
    seen = []

    def edit(spec):
        seen.append(spec.model_dump(mode="json"))
        return discover.ScreenSpec.model_validate({
            "rank_by": "revenue", "filters": [{"metric": "revenue", "op": ">", "value": 0}], "top_k": 1,
            "terms": [cheap | {"definition": "P/E below 12"}, LARGE]})
    result, client, events = find(tmp_path, declared, spec(**draft), *research("AAPL", "0000320193"),
                                  ask=lambda term: "", edit=edit)
    assert seen[0]["terms"][0]["definition"] == "P/E below 20" and len(client.requests) == 5  # spec, then research
    assert result.interpretation.spec.rank_by == "revenue"
    assert result.interpretation.sources == {"cheap": "user", "large": "accepted"}
    questions = next(e for e in events if e["kind"] == "questions")
    assert questions["spec"]["terms"][0]["term"] == "cheap"
    assert next(e for e in events if e["kind"] == "spec_edit")["spec"]["rank_by"] == "revenue"


def test_a_spec_with_no_vague_terms_still_waits_for_review_when_asked(tmp_path, declared):
    shown = []
    result, _, events = find(tmp_path, declared, spec(top_k=1), *research("AAPL", "0000320193"),
                             ask=lambda term: pytest.fail("no terms"), edit=lambda s: shown.append(s) or None,
                             review=True)
    assert len(shown) == 1 and [e["terms"] for e in events if e["kind"] == "questions"] == [[]]
    assert not [e for e in events if e["kind"] == "spec_edit"] and result.interpretation.spec.top_k == 1


def test_each_vague_term_offers_options_and_its_definition_is_the_recommended_one():
    from research_assistant.agents.discover_spec import Term
    cheap = {"term": "cheap", "definition": "P/E below 15", "question": "What P/E is cheap?"}
    marked_wrong = Term(**cheap, options=[{"definition": "P/E below 15"}, {"definition": "P/E below 25", "recommended": True}])
    assert [(o.definition, o.recommended) for o in marked_wrong.options] == [("P/E below 15", True), ("P/E below 25", False)]
    reworded = Term(**cheap, options=[{"definition": "P/E under 15", "recommended": True}, {"definition": "P/E below 25"}])
    assert [(o.definition, o.recommended) for o in reworded.options] == [("P/E below 15", True), ("P/E below 25", False)]
    missing = Term(**cheap, options=[{"definition": "P/E below 25"}, {"definition": "P/S below 3"}])
    assert [o.definition for o in missing.options] == ["P/E below 15", "P/E below 25", "P/S below 3"]
    assert missing.options[0].recommended and not any(o.recommended for o in missing.options[1:])
    assert Term(**cheap).options == []  # no options: the page and terminal ask for free text, as before


def test_the_full_sp500_is_bundled_with_its_date_sectors_and_survivorship_note():
    sp500 = universe.load("sp500")
    assert len(sp500.members) == 503 and len(sp500.ciks) == 500  # GOOG/GOOGL, FOX/FOXA, NWS/NWSA
    assert len({m.sector for m in sp500.members}) == 11 and all(m.sector for m in sp500.members)
    assert sp500.as_of == "2026-11-05" and "wikipedia" in sp500.source and "survivorship" in sp500.note
    tickers = {m.ticker for m in sp500.members}
    assert {"BRK-B", "BF-B", "ON", "T"} <= tickers and not any("." in t for t in tickers)  # SEC's ticker style
    assert set(universe.load("sp500_tech").ciks) <= set(sp500.ciks)


def test_the_saved_shortlist_gives_each_candidate_its_tickers_for_compare_these(tmp_path, declared):
    from research_assistant.agents import saved
    result, _, _ = find(tmp_path, declared, spec(rank_by="revenue", filters=[{"metric": "revenue", "op": ">", "value": 0}],
                                                top_k=1), *research("AAPL", "0000320193"))
    candidates = saved.report(result.trace_path)["discover"]["candidates"]
    apple = next(c for c in candidates if c["cik"] == "0000320193")
    assert apple["outcome"] == "picked" and apple["tickers"] == ["AAPL"]


def test_every_sec_filer_with_a_ticker_is_a_universe_described_without_its_member_list(tmp_path):
    from research_assistant.agents.discover_spec import describe
    from research_assistant.data.companies import listed_companies
    sec = make_context(tmp_path).sec
    everyone = universe.load(universe.ALL_FILERS, sec)
    listed = listed_companies(sec)
    assert len(everyone.ciks) == len(listed) and not everyone.show_members and "survivorship" in everyone.note
    assert len(everyone.members) == sum(len(c.tickers) for c in listed.values())
    text = describe(everyone)
    assert f"{len(everyone.ciks)} companies" in text and "aren't listed here" in text and "- AAPL:" not in text
    assert "- AAPL: Apple Inc." in describe(universe.load("sp500"))
    with pytest.raises(universe.UniverseError, match="needs SEC access"):
        universe.load(universe.ALL_FILERS)
