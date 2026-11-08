import re
from pathlib import Path

import httpx
import openai
import pytest
from fake_llm import FakeClient, reply, resubmit
from sec_files import make_context

from research_assistant import cli, config
from research_assistant.model_access import ModelSettings

REPORT = {"summary": [{"text": "Apple Inc. files annual reports with the SEC.", "citations": ["company-0000320193"]}]}


def configure(monkeypatch, tmp_path, client):
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("RESEARCH_MODEL", "fake-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(cli, "sec_client", lambda: make_context(tmp_path).sec)
    monkeypatch.setattr(cli, "model_client", lambda settings: client)


def test_a_question_prints_the_report_and_where_the_trace_is(tmp_path, monkeypatch, capsys):
    client = FakeClient(reply("1. find_company"), reply(tool_calls=[("find_company", {"query": "AAPL"})]),
                        reply(tool_calls=[("submit_report", REPORT)]), resubmit)
    configure(monkeypatch, tmp_path, client)
    assert cli.main(["Who is Apple?", "--cutoff", "2026-11-01"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("# Who is Apple?\n") and "- Cutoff: 2026-11-01T23:59:59.999999+00:00" in out
    assert "- Apple Inc. files annual reports with the SEC. [1]" in out
    trace = Path(re.search(r"^Trace saved to (.+)$", out, re.MULTILINE)[1])
    assert trace.is_file() and trace.parent == tmp_path / "traces"
    assert "plan ready" in err and "step 1: asked for company lookup" in err and "checker: 0 flags" in err
    assert 'step 1: Company lookup: "AAPL" → OK, Apple Inc. (AAPL)' in err and "step 2: handing in the report" in err


def test_condition_c_runs_the_team_and_says_who_did_each_step(tmp_path, monkeypatch, capsys):
    def findings(messages):
        return reply(tool_calls=[("submit_findings", {"findings": [REPORT["summary"][0]]})])

    client = FakeClient(reply("1. ask_fundamentals"), reply(tool_calls=[("ask_fundamentals", {"task": "Who is Apple?"})]),
                        reply(tool_calls=[("find_company", {"query": "AAPL"})]), findings,
                        reply(tool_calls=[("submit_report", REPORT)]), resubmit)
    configure(monkeypatch, tmp_path, client)
    assert cli.main(["Who is Apple?", "--condition", "C"]) == 0
    out, err = capsys.readouterr()
    assert "- Condition: C (analyst team)" in out and "- Apple Inc. files annual reports with the SEC. [1]" in out
    for line in ("[coordinator] plan ready", "[fundamentals] task: Who is Apple?",
                 '[fundamentals] step 1: Company lookup: "AAPL" → OK', "[fundamentals] done (finished): 1 findings",
                 "[coordinator] step 1: Fundamentals analyst → OK, 1 finding, 0 gaps", "[coordinator] checker: 0 flags"):
        assert line in err


def test_a_failed_run_exits_1(tmp_path, monkeypatch, capsys):
    configure(monkeypatch, tmp_path, FakeClient(openai.APIConnectionError(request=httpx.Request("POST", "https://x"))))
    assert cli.main(["Who is Apple?"]) == 1
    out, _ = capsys.readouterr()
    assert "- Run status: failed" in out and "Trace saved to" in out


def test_missing_model_settings_explain_what_to_set(capsys):
    assert cli.main(["Who is Apple?"]) == 2
    assert "RESEARCH_MODEL" in capsys.readouterr().err


def test_the_agent_model_client_retries_patiently():
    settings = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")
    with cli.model_client(settings) as client:
        assert client.max_retries == config.AGENT_MODEL_RETRIES > 2


def test_no_question_serves_the_web_app(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    assert cli.main([]) == 0
    assert calls == [("research_assistant.api:create_app",
                      {"factory": True, "host": "127.0.0.1", "port": 8000, "workers": 1})]


def test_universe_runs_discover_and_shows_the_spec_before_research(tmp_path, monkeypatch, capsys):
    path = tmp_path / "two.yaml"
    path.write_text('name: Two\nsource: tests\nas_of: 2026-11-03\nnote: A test list.\ncompanies:\n'
                    '  - {ticker: "AAPL", cik: "0000320193", name: Apple}\n'
                    '  - {ticker: "JPM", cik: "0000019617", name: JPMorgan}\n', encoding="utf-8")
    valuation = {"term": "reasonable valuation", "definition": "P/E below 40", "question": "What P/E?"}
    spec = {"rank_by": "operating_margin", "filters": [{"metric": "operating_margin", "op": ">", "value": 0.25}],
            "terms": [valuation]}
    client = FakeClient(reply(tool_calls=[("submit_screen_spec", spec)]))
    configure(monkeypatch, tmp_path, client)
    assert cli.main(["Find profitable tech at a reasonable valuation.", "--universe", str(path),
                     "--define", "reasonable valuation=P/E below 40"]) == 0
    out, err = capsys.readouterr()
    assert "## Screen spec" in out and '"reasonable valuation" read as: P/E below 40 (set by the user)' in out
    assert "- reasonable valuation: P/E below 40" in client.requests[0]["messages"][1]["content"]
    assert "\nscreen spec:\n  - Universe: Two" in err and "[host] Screen: 2 companies, 1 filter, ranked by" in err
    assert err.index("screen spec:") < err.index("[host] Screen:")


def test_discover_refuses_a_past_cutoff_and_malformed_definitions(capsys):
    for argv in (["Find tech.", "--universe", "sp500_tech", "--cutoff", "2025-01-01"],
                 ["Find tech.", "--universe", "sp500_tech", "--define", "cheap"],
                 ["Who is Apple?", "--define", "cheap=P/E below 15"]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "current data only" in err and "TERM=MEANING" in err and "need --universe" in err


def test_an_unknown_universe_names_the_bundled_ones(capsys):
    assert cli.main(["Find tech.", "--universe", "nope"]) == 2
    assert "sp500_tech" in capsys.readouterr().err


def test_a_past_cutoff_makes_screen_refuse_and_a_live_run_does_not(tmp_path, monkeypatch, capsys):
    def script():
        return FakeClient(reply("1. screen"), reply(tool_calls=[("screen", {"universe": ["AAPL"], "rank_by": "revenue",
                                                                            "year": 2024})]),
                          reply(tool_calls=[("submit_report", REPORT)]), resubmit)
    configure(monkeypatch, tmp_path, script())
    assert cli.main(["Rank Apple.", "--cutoff", "2026-11-01"]) == 0
    assert "step 1: Screen → invalid: " in capsys.readouterr().err
    configure(monkeypatch, tmp_path, script())
    assert cli.main(["Rank Apple."]) == 0
    assert "step 1: Screen: " in capsys.readouterr().err


def test_the_terminal_offers_each_terms_options_by_number(monkeypatch, capsys):
    from research_assistant.agents.discover_spec import Term
    term = Term(term="cheap", definition="P/E below 15", question="What P/E is cheap?",
                options=[{"definition": "P/E below 15"}, {"definition": "P/E below 25"}])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    for typed, expected in (["2"], "P/E below 25"), (["1"], ""), ([""], ""), (["9", "2"], "P/E below 25"), \
                           (["P/S below 3"], "P/S below 3"):
        monkeypatch.setattr("builtins.input", iter(typed).__next__)
        assert cli.ask_user(term) == expected, typed
    shown = capsys.readouterr().err
    assert "  1. P/E below 15 (recommended)\n  2. P/E below 25\n" in shown and "Pick 1 to 2" in shown
    plain = Term(term="large", definition="revenue over $10 billion", question="What is large?")
    monkeypatch.setattr("builtins.input", lambda: "")
    assert cli.ask_user(plain) == "" and "Proposed: revenue over $10 billion" in capsys.readouterr().err
