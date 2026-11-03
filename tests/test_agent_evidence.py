import copy
import json
from collections import Counter

import pandas as pd
import pytest
from fake_llm import FakeClient, reply, resubmit, tool_results
from sec_files import make_context

from research_assistant import cli
from research_assistant.agents import evidence, single_agent
from research_assistant.data import prices_yfinance
from research_assistant.model_access import ModelSettings

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")


def history(adj_close):
    days = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"])
    frame = pd.DataFrame({"Close": [10.0, 11.0, 12.0, 13.0], "Adj Close": adj_close,
                          "Volume": [1.0] * 4, "Dividends": [0.0] * 4, "Stock Splits": [0.0] * 4}, index=days)
    return lambda ticker, start, end: (frame, pd.Series(dtype=float))


@pytest.fixture(autouse=True)
def yahoo(monkeypatch):
    monkeypatch.setattr(prices_yfinance, "_history", history([9.0, 10.0, 11.5, 12.0]))


def saved_run(tmp_path):
    """A run whose report cites a volatility computed from a price series, with the series fetched twice."""
    def volatility(messages):
        series = tool_results(messages)[-1]["ids"][0]
        return reply(tool_calls=[("calculate", {"formula": "volatility", "inputs": {"prices": series}})])

    def submit(messages):
        calc = tool_results(messages)[-1]["ids"][0]
        return reply(tool_calls=[("submit_report", {"summary": [{"text": "Volatility was {calc:%s}." % calc}]})])

    prices = reply(tool_calls=[("get_prices", {"ticker": "AAPL"})])
    client = FakeClient(reply("1. get_prices"), prices, prices, volatility, submit, resubmit)
    return single_agent.run("How volatile is Apple?", client, SETTINGS, make_context(tmp_path),
                            trace_dir=tmp_path / "traces")


def rewrite(path, change):
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        change(event)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def test_the_trace_freezes_every_record_in_full_once(tmp_path):
    result = saved_run(tmp_path)
    saved = evidence.load(result.trace_path)
    prices = next(r for r in saved.records.values() if r["kind"] == "prices")
    assert [row["adj_close"] for row in prices["rows"]] == [9.0, 10.0, 11.5, 12.0]  # every daily row, not a summary
    calc = next(r for r in saved.records.values() if r["kind"] == "calc")
    assert calc["inputs"] == {"prices": prices["id"]} and calc["value"] is not None
    written = Counter(i for e in saved.events if e["kind"] == "tool_call" for i in e["records"])
    assert written == {prices["id"]: 1, calc["id"]: 1}  # the repeated get_prices wrote nothing again
    assert saved.end["draft"]["summary"][0]["text"] == "Volatility was {calc:%s}." % calc["id"]


def test_a_saved_run_is_rechecked_offline_and_a_changed_input_is_caught(tmp_path, monkeypatch):
    path = saved_run(tmp_path).trace_path
    monkeypatch.setattr(prices_yfinance, "_history", lambda *a: pytest.fail("the recheck must not fetch prices"))
    clean = evidence.recheck(path)
    assert (clean.calcs, clean.statements, clean.problems) == (1, 1, [])

    def double_a_close(event):
        for record in (event.get("records") or {}).values():
            if record["kind"] == "prices":
                record["rows"][2]["adj_close"] = 23.0
    rewrite(path, double_a_close)
    [problem] = evidence.recheck(path).problems
    assert "(volatility) was saved as" in problem and "recomputes to" in problem

    def edit_the_report(event):
        if event["kind"] == "run_end":
            event["report"]["sections"]["summary"][0]["text"] = "Volatility was 1%."
    rewrite(path, edit_the_report)
    assert any("but the saved report has 'Volatility was 1%.'" in p for p in evidence.recheck(path).problems)


def test_a_series_fetched_again_with_other_closes_gets_its_own_id(tmp_path, monkeypatch):
    """Seen live on 3 Nov 2026: an analyst fetched a series again and Yahoo's adjusted closes came back with float
    noise. Under one ID the trace kept only the later rows, so a beta made from the first rows didn't recheck."""
    def volatility_then_fetch_again(messages):
        monkeypatch.setattr(prices_yfinance, "_history", history([9.0, 10.0, 11.6, 12.0]))
        series = tool_results(messages)[-1]["ids"][0]
        return reply(tool_calls=[("calculate", {"formula": "volatility", "inputs": {"prices": series}}),
                                 ("get_prices", {"ticker": "AAPL", "start": "2026-03-01"})])

    def submit(messages):
        calc = tool_results(messages)[-2]["ids"][0]
        return reply(tool_calls=[("submit_report", {"summary": [{"text": "Volatility was {calc:%s}." % calc}]})])

    client = FakeClient(reply("1. get_prices"), reply(tool_calls=[("get_prices", {"ticker": "AAPL"})]),
                        volatility_then_fetch_again, submit, resubmit)
    path = single_agent.run("How volatile is Apple?", client, SETTINGS, make_context(tmp_path),
                            trace_dir=tmp_path / "traces").trace_path
    saved = evidence.load(path)
    first, again = [r for r in saved.records.values() if r["kind"] == "prices"]
    assert first["id"] != again["id"] and again["rows"][2]["adj_close"] == 11.6
    calc = next(r for r in saved.records.values() if r["kind"] == "calc")
    assert calc["inputs"] == {"prices": first["id"]}
    assert evidence.recheck(path).problems == []


def test_a_trace_holding_two_versions_under_one_id_still_rechecks(tmp_path):
    """Traces saved before a price ID covered its rows (e.g. 20261103-092422-ca0f2d) hold a refetched series twice
    under one ID. Each calculation is recomputed from the versions frozen under its inputs' IDs."""
    path = saved_run(tmp_path).trace_path
    prices = next(r for r in evidence.load(path).records.values() if r["kind"] == "prices")
    refetched = copy.deepcopy(prices)
    refetched["rows"][2]["adj_close"] = 11.6
    with path.open("a", encoding="utf-8") as file:  # the refetch comes after the calculation, as it did live
        file.write(json.dumps({"seq": 99, "kind": "tool_call", "records": {prices["id"]: refetched}}) + "\n")
    saved = evidence.load(path)
    assert saved.records[prices["id"]] == refetched and saved.versions[prices["id"]] == [prices, refetched]
    assert (evidence.recheck(path).calcs, evidence.recheck(path).problems) == (1, [])

    def tamper(event):
        for record in (event.get("records") or {}).values():
            if record["kind"] == "calc":
                record["value"] = 0.5
    rewrite(path, tamper)  # no version of the series gives 0.5
    assert any("(volatility) was saved as 0.5 but recomputes to" in p for p in evidence.recheck(path).problems)


def test_the_cli_rechecks_a_trace(tmp_path, capsys):
    path = saved_run(tmp_path).trace_path
    assert cli.main(["--recheck", str(path)]) == 0
    assert "Rechecked 1 calculations and 1 report statements" in capsys.readouterr().out
    old = tmp_path / "old.jsonl"
    old.write_text(json.dumps({"kind": "run_start", "cutoff": "2026-11-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
    assert cli.main(["--recheck", str(old)]) == 1
    assert "holds no tool records" in capsys.readouterr().out
