from datetime import date, datetime, timezone

from sec_files import SecFiles, make_context

from research_assistant.tools.list_filings import ListFilingsInput, run

OLDER_PAGE = "/submissions/CIK0000320193-submissions-001.json"


def listed(tmp_path, cutoff=None, files=None, **args):
    context = make_context(tmp_path, files=files, **({"cutoff": cutoff} if cutoff else {}))
    return run(ListFilingsInput(cik="320193", **args), context), context


def test_8k_events_have_item_names_and_event_dates(tmp_path):
    result, context = listed(tmp_path, forms=["8-k"])
    first = result.data["filings"][0]
    assert result.status == "ok" and first["form"] == "8-K"
    assert first["items"] == [{"code": "2.02", "name": "Results of operations and financial condition"},
                              {"code": "9.01", "name": "Financial statements and exhibits"}]
    assert first["accepted_at"] == "2026-07-30T20:30:28+00:00" and first["report_date"] == "2026-07-30"
    assert first["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    assert context.records[first["id"]]["kind"] == "filing"


def test_newest_first_and_recent_block_only_when_enough(tmp_path):
    files = SecFiles()
    result, _ = listed(tmp_path, files=files, limit=3)
    filed = [f["filed"] for f in result.data["filings"]]
    assert filed == sorted(filed, reverse=True) and len(filed) == 3
    assert OLDER_PAGE not in files.paths
    assert any("before=" in w for w in result.warnings)


def test_old_filings_come_from_the_older_pages(tmp_path):
    files = SecFiles()
    result, _ = listed(tmp_path, files=files, forms=["10-K"], limit=5)
    assert [f["filed"] for f in result.data["filings"]][-1] == "2014-10-27"
    assert OLDER_PAGE in files.paths


def test_since_stops_before_reading_older_pages(tmp_path):
    files = SecFiles()
    listed(tmp_path, files=files, since=date(2025, 1, 1))
    assert OLDER_PAGE not in files.paths


def test_acceptance_time_enforces_the_cutoff_to_the_second(tmp_path):
    before = datetime(2026, 7, 30, 20, 30, 27, tzinfo=timezone.utc)
    result, _ = listed(tmp_path, cutoff=before, forms=["8-K"], limit=1)
    assert result.data["filings"][0]["filed"] < "2026-07-30"
