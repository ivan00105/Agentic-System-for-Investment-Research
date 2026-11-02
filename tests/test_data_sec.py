import json
import threading
from datetime import datetime, timedelta

import httpx
import pytest

from research_assistant import config
from research_assistant.data import sec
from research_assistant.data.sec import RateLimiter, SecClient, SecError

AGENT = "Fieldnote test@example.com"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
FILING = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


class Network:
    """Stands in for SEC: answers from a script (the last answer repeats) and records each request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class CountingLimiter:
    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1


def client(tmp_path, network, user_agent=AGENT, limiter=None, sleeps=None):
    return SecClient(user_agent, tmp_path / "cache", transport=httpx.MockTransport(network),
                     limiter=limiter or CountingLimiter(), sleep=sleeps.append if sleeps is not None else lambda s: None)


def cache_files(tmp_path):
    return list((tmp_path / "cache").glob("*"))


def age_cache(tmp_path, days):
    for meta in (tmp_path / "cache").glob("*.json"):
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["retrieved_at"] = (datetime.fromisoformat(data["retrieved_at"]) - timedelta(days=days)).isoformat()
        meta.write_text(json.dumps(data), encoding="utf-8")


# --- requests ---------------------------------------------------------------------------

def test_sends_user_agent_and_returns_parsed_json(tmp_path):
    network = Network(httpx.Response(200, json={"cik": 320193}))
    response = client(tmp_path, network).companyfacts(320193)
    assert response.json() == {"cik": 320193}
    assert response.url == FACTS and not response.from_cache
    assert network.requests[0].headers["User-Agent"] == AGENT


def test_cik_is_zero_padded_in_api_paths(tmp_path):
    network = Network(httpx.Response(200, json={}))
    client(tmp_path, network).submissions("320193")
    assert str(network.requests[0].url) == "https://data.sec.gov/submissions/CIK0000320193.json"


@pytest.mark.parametrize("bad", ["AAPL", "", "12345678901", "-1", "３２"])
def test_invalid_cik_is_rejected(bad):
    with pytest.raises(ValueError):
        sec.cik10(bad)


@pytest.mark.parametrize("url", ["http://data.sec.gov/x.json", "https://example.com/x.json", "https://data.sec.gov.example.com/x"])
def test_only_sec_https_urls_are_fetched(tmp_path, url):
    network = Network(httpx.Response(200))
    with pytest.raises(ValueError):
        client(tmp_path, network).get(url)
    assert network.requests == []


# --- configuration ----------------------------------------------------------------------

@pytest.mark.parametrize("agent", [None, "", "Fieldnote no-email"])
def test_missing_user_agent_is_not_configured_and_sends_nothing(tmp_path, agent):
    network = Network(httpx.Response(200))
    sec_client = client(tmp_path, network, user_agent=agent)
    assert not sec_client.configured
    with pytest.raises(SecError) as error:
        sec_client.get(FACTS)
    assert error.value.code == "not_configured" and "SEC_USER_AGENT" in str(error.value)
    assert network.requests == []


def test_user_agent_comes_from_environment_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", AGENT)
    network = Network(httpx.Response(200))
    client(tmp_path, network, user_agent=None).get(FACTS)
    assert network.requests[0].headers["User-Agent"] == AGENT


def test_cached_responses_work_without_user_agent(tmp_path):
    client(tmp_path, Network(httpx.Response(200, content=b"facts"))).get(FACTS)
    offline = Network(httpx.Response(500))
    assert client(tmp_path, offline, user_agent="").get(FACTS).body == b"facts"
    assert offline.requests == []


# --- disk cache -------------------------------------------------------------------------

def test_repeat_request_is_served_from_disk_cache_across_clients(tmp_path):
    network = Network(httpx.Response(200, content=b"facts"))
    first = client(tmp_path, network).get(FACTS)
    again = client(tmp_path, network).get(FACTS)
    assert again.body == b"facts" and again.from_cache
    assert again.retrieved_at == first.retrieved_at
    assert len(network.requests) == 1


def test_cache_hits_skip_the_rate_limiter(tmp_path):
    limiter = CountingLimiter()
    sec_client = client(tmp_path, Network(httpx.Response(200, content=b"facts")), limiter=limiter)
    sec_client.get(FACTS)
    sec_client.get(FACTS)
    assert limiter.calls == 1


def test_stale_api_response_is_refetched(tmp_path):
    network = Network(httpx.Response(200, content=b"old"), httpx.Response(200, content=b"new"))
    sec_client = client(tmp_path, network)
    sec_client.get(FACTS)
    age_cache(tmp_path, days=2)
    assert sec_client.get(FACTS).body == b"new"
    assert sec_client.get(FACTS).from_cache


def test_archived_filings_never_expire(tmp_path):
    network = Network(httpx.Response(200, content=b"10-K"))
    sec_client = client(tmp_path, network)
    sec_client.get(FILING)
    age_cache(tmp_path, days=3650)
    assert sec_client.get(FILING).from_cache
    assert len(network.requests) == 1


def test_corrupt_cache_entry_is_refetched(tmp_path):
    network = Network(httpx.Response(200, content=b"good"))
    sec_client = client(tmp_path, network)
    sec_client.get(FACTS)
    for body in (tmp_path / "cache").glob("*.body"):
        body.write_bytes(b"torn")
    assert sec_client.get(FACTS).body == b"good"
    assert len(network.requests) == 2


def test_unwritable_cache_still_returns_the_response(tmp_path):
    (tmp_path / "cache").write_text("a file where the cache folder should be", encoding="utf-8")
    response = client(tmp_path, Network(httpx.Response(200, content=b"facts"))).get(FACTS)
    assert response.body == b"facts" and not response.from_cache


# --- errors and retries -----------------------------------------------------------------

def test_transient_errors_are_retried_with_doubling_backoff(tmp_path):
    sleeps, limiter = [], CountingLimiter()
    network = Network(httpx.Response(503), httpx.Response(429), httpx.ConnectError("blip"), httpx.Response(200, content=b"ok"))
    assert client(tmp_path, network, limiter=limiter, sleeps=sleeps).get(FACTS).body == b"ok"
    assert sleeps == [1.0, 2.0, 4.0]
    assert limiter.calls == 4


def test_gives_up_after_configured_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEC_RETRIES", 1)
    network = Network(httpx.Response(503))
    with pytest.raises(SecError) as error:
        client(tmp_path, network).get(FACTS)
    assert (error.value.code, error.value.status) == ("http_error", 503)
    assert len(network.requests) == 2
    assert cache_files(tmp_path) == []


def test_network_failure_after_retries_is_a_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEC_RETRIES", 0)
    with pytest.raises(SecError) as error:
        client(tmp_path, Network(httpx.ReadTimeout("slow"))).get(FACTS)
    assert error.value.code == "network"


@pytest.mark.parametrize(("status", "code"), [(404, "not_found"), (403, "http_error"), (301, "http_error")])
def test_other_statuses_fail_at_once_and_are_not_cached(tmp_path, status, code):
    network = Network(httpx.Response(status))
    with pytest.raises(SecError) as error:
        client(tmp_path, network).get(FACTS)
    assert (error.value.code, error.value.status) == (code, status)
    assert len(network.requests) == 1
    assert cache_files(tmp_path) == []


def test_oversized_response_is_an_error_naming_the_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEC_MAX_RESPONSE_BYTES", 4)
    with pytest.raises(SecError) as error:
        client(tmp_path, Network(httpx.Response(200, content=b"12345"))).get(FACTS)
    assert error.value.code == "too_large" and "SEC_MAX_RESPONSE_BYTES" in str(error.value)
    assert cache_files(tmp_path) == []


# --- rate limit -------------------------------------------------------------------------

class FakeTime:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def test_rate_limiter_spaces_calls_at_the_configured_rate():
    time = FakeTime()
    limiter = RateLimiter(10, clock=time.clock, sleep=time.sleep)
    for _ in range(3):
        limiter.wait()
    assert time.sleeps == [0.1, 0.1]


def test_rate_limiter_does_not_wait_after_a_pause():
    time = FakeTime()
    limiter = RateLimiter(10, clock=time.clock, sleep=time.sleep)
    limiter.wait()
    time.now = 5.0
    limiter.wait()
    assert time.sleeps == []


def test_rate_limiter_gives_concurrent_callers_separate_slots():
    sleeps = []
    limiter = RateLimiter(10, clock=lambda: 0.0, sleep=lambda s: sleeps.append(round(s, 6)))
    threads = [threading.Thread(target=limiter.wait) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(sleeps) == [round(0.1 * i, 6) for i in range(1, 20)]


def test_clients_share_the_process_wide_limiter_by_default(tmp_path, monkeypatch):
    shared = CountingLimiter()
    monkeypatch.setattr(sec, "LIMITER", shared)
    for name in ("first", "second"):
        SecClient(AGENT, tmp_path / name, transport=httpx.MockTransport(Network(httpx.Response(200)))).get(FACTS)
    assert shared.calls == 2
