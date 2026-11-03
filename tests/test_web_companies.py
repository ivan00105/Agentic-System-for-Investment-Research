import pytest
from fastapi.testclient import TestClient
from sec_files import SecFiles, make_context

from research_assistant import cli, config
from research_assistant.api import create_app
from research_assistant.data.sec import SecClient


@pytest.fixture
def web(tmp_path, monkeypatch):
    files = SecFiles()
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "sec_client", lambda: make_context(tmp_path, files=files).sec)
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as web:
        web.files = files
        yield web


def names(web, q):
    response = web.get("/api/companies", params={"q": q})
    assert response.status_code == 200, response.text
    return [(item["name"], item["tickers"]) for item in response.json()["items"]]


def test_tickers_starting_with_the_text_come_first_largest_first(web):
    assert names(web, "aap")[0] == ("Apple Inc.", ["AAPL"])
    assert names(web, "ap")[:2] == [("Apple Hospitality REIT, Inc.", ["APLE"]), ("Apple Inc.", ["AAPL"])]
    assert names(web, "googl") == [("Alphabet Inc.", ["GOOGL", "GOOG"])]  # share classes are one company


def test_names_match_when_no_ticker_does_and_the_all_filers_list_is_never_fetched(web):
    assert names(web, "apple")[0] == ("Apple Inc.", ["AAPL"])
    assert names(web, "zzzz-no-such-company") == []
    assert names(web, "   ") == []
    assert not any("cik-lookup-data" in path for path in web.files.paths)


def test_more_matches_than_shown_are_counted(web, monkeypatch):
    monkeypatch.setattr(config, "COMPANY_SUGGEST_MAX", 1)
    body = web.get("/api/companies", params={"q": "a"}).json()
    assert len(body["items"]) == 1 and body["total"] > 1


def test_search_without_sec_access_says_what_to_set(web, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "sec_client", lambda: SecClient("", tmp_path / "empty"))
    response = web.get("/api/companies", params={"q": "apple"})
    assert response.status_code == 409 and "SEC_USER_AGENT" in response.json()["error"]["message"]


def test_the_bundled_discover_universes_are_listed_with_their_size(web):
    [tech] = [u for u in web.get("/api/universes").json()["items"] if u["id"] == "sp500_tech"]
    assert tech["companies"] > 50 and tech["name"].startswith("S&P 500") and tech["as_of"]
