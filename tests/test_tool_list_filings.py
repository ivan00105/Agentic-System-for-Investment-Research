from datetime import date, datetime, timezone

import pytest
from sec_files import ABNB_IPO, ABNB_SUBMISSIONS, SecFiles, make_context, submissions

from research_assistant.data.sec_filings import RELEASED_LATER, Filing
from research_assistant.tools.list_filings import ListFilingsInput, run

OLDER_PAGE = "/submissions/CIK0000320193-submissions-001.json"


def listed(tmp_path, cutoff=None, files=None, cik="320193", **args):
    context = make_context(tmp_path, files=files, **({"cutoff": cutoff} if cutoff else {}))
    return run(ListFilingsInput(cik=cik, **args), context), context


def airbnb(tmp_path, **args):
    return listed(tmp_path, files=SecFiles({ABNB_SUBMISSIONS: submissions(ABNB_IPO)}), cik="1559720", **args)[0]


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
    assert result.data["next_page"] and any("page=" in w for w in result.warnings)


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


def test_paging_never_skips_filings_from_the_same_day(tmp_path):
    # Codex review: with before=<date>, the other filings of the boundary day were skipped.
    import json

    import httpx
    from sec_files import FIXTURES

    payload = json.loads((FIXTURES / "submissions_AAPL.json").read_text())
    recent = payload["filings"]["recent"]
    newest = max(range(len(recent["filingDate"])), key=lambda i: recent["filingDate"][i])
    twin = next(i for i in range(len(recent["filingDate"])) if i != newest)
    recent["filingDate"][twin] = recent["filingDate"][newest]
    recent["acceptanceDateTime"][twin] = recent["acceptanceDateTime"][newest]
    files = SecFiles({"/submissions/CIK0000320193.json": httpx.Response(200, json=payload)})
    first, _ = listed(tmp_path, files=files, limit=1)
    second, _ = listed(tmp_path, files=files, limit=1, page=first.data["next_page"])
    shown = {first.data["filings"][0]["accession"], second.data["filings"][0]["accession"]}
    assert shown == {recent["accessionNumber"][newest], recent["accessionNumber"][twin]}


def test_drafts_and_review_letters_are_not_listed_before_sec_released_them(tmp_path):
    # Airbnb's DRS, DRS/A, DRSLTR and UPLOAD are dated August-September 2020; the public S-1 came on 16 November.
    before_the_s1 = datetime(2020, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    result = airbnb(tmp_path, cutoff=before_the_s1)
    assert result.data["filings"] == [] and result.warnings == ["No filings match before the cutoff."]


def test_forms_released_later_stay_out_at_any_cutoff(tmp_path):
    assert [f["form"] for f in airbnb(tmp_path).data["filings"]] == ["S-1/A", "S-1"]


def test_asking_for_a_form_released_later_says_why_it_is_missing(tmp_path):
    result = airbnb(tmp_path, forms=["drs", "S-1"])
    assert [f["form"] for f in result.data["filings"]] == ["S-1"]
    assert [w for w in result.warnings if w.startswith("DRS never listed: SEC publishes these forms")]


@pytest.mark.parametrize("form", sorted(RELEASED_LATER))
def test_a_form_released_later_is_never_public_at_a_cutoff(form):
    accepted = datetime(2020, 8, 19, 20, 18, 11, tzinfo=timezone.utc)
    filing = Filing("0001559720", "0000950123-20-009252", form, accepted.date(), accepted, None, (), "filename1.htm", "")
    assert not filing.public_by(datetime.max.replace(tzinfo=timezone.utc))
