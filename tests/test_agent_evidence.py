import json
from collections import Counter

import pandas as pd
import pytest
from fake_llm import FakeClient, reply, tool_results
from sec_files import make_context

from research_assistant import cli
from research_assistant.agents import evidence, single_agent
from research_assistant.data import prices_yfinance
from research_assistant.model_access import ModelSettings

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")


@pytest.fixture(autouse=True)
def yahoo(monkeypatch):
    days = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"])
    frame = pd.DataFrame({"Close": [10.0, 11.0, 12.0, 13.0], "Adj Close": [9.0, 10.0, 11.5, 12.0],
                          "Volume": [1.0] * 4, "Dividends": [0.0] * 4, "Stock Splits": [0.0] * 4}, index=days)
    monkeypatch.setattr(prices_yfinance, "_history", lambda ticker, start, end: (frame, pd.Series(dtype=float)))


def saved_run(tmp_path):
    """A run whose report cites a volatility computed from a price series, with the series fetched twice."""
    def volatility(messages):
        series = tool_results(messages)[-1]["ids"][0]
        return reply(tool_calls=[("calculate", {"formula": "volatility", "inputs": {"prices": series}})])

    def submit(messages):
        calc = tool_results(messages)[-1]["ids"][0]
        return reply(tool_calls=[("submit_report", {"summary": [{"text": "Volatility was {calc:%s}." % calc}]})])

    prices = reply(tool_calls=[("get_prices", {"ticker": "AAPL"})])
    client = FakeClient(reply("1. get_prices"), prices, prices, volatility, submit)
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


def test_the_cli_rechecks_a_trace(tmp_path, capsys):
    path = saved_run(tmp_path).trace_path
    assert cli.main(["--recheck", str(path)]) == 0
    assert "Rechecked 1 calculations and 1 report statements" in capsys.readouterr().out
    old = tmp_path / "old.jsonl"
    old.write_text(json.dumps({"kind": "run_start", "cutoff": "2026-11-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
    assert cli.main(["--recheck", str(old)]) == 1
    assert "holds no tool records" in capsys.readouterr().out
