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
    assert "plan ready" in err and "step 1: find_company -> ok" in err and "checker: 0 flags" in err


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
                 "[fundamentals] step 1: find_company -> ok", "[fundamentals] done (finished): 1 findings",
                 "[coordinator] step 1: ask_fundamentals -> ok", "[coordinator] checker: 0 flags"):
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
    assert "\nscreen spec:\n  - Universe: Two" in err and "[host] screen -> ok" in err
    assert err.index("screen spec:") < err.index("[host] screen -> ok")


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
