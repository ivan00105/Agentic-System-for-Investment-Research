"""Synthetic Form 4 filings for a mocked SEC: never live evidence."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
from sec_files import FIXTURES, SecFiles, make_context

from research_assistant.agents.acceptance import Acceptance
from research_assistant.agents.discover_spec import PriceCheck
from research_assistant.agents.report import describe
from research_assistant.agents.sources import detail
from research_assistant.agents.trace import Trace
from research_assistant.data import providers
from research_assistant.tools.get_insider_trades import GetInsiderTradesInput, run

CUTOFF = datetime(2026, 11, 6, 23, tzinfo=timezone.utc)
FOLDER = "/Archives/edgar/data/320193/{}/form4.xml"


def form4(owner, role, rows, plan_box=False, derivative=(), footnote="Sold under a Rule 10b5-1 trading plan."):
    trades = "".join(f"""<nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>{day}</value></transactionDate>
        <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare>{f'<value>{price}</value>' if price else '<footnoteId id="F2"/>'}</transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{'A' if code in 'PM' else 'D'}</value></transactionAcquiredDisposedCode></transactionAmounts>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
        <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
        {'<footnoteId id="F1"/>' if note else ''}</nonDerivativeTransaction>""" for day, code, shares, price, note in rows)
    options = "".join(f"<derivativeTransaction><transactionCoding><transactionCode>{c}</transactionCode></transactionCoding>"
                      "</derivativeTransaction>" for c in derivative)
    return f"""<?xml version="1.0"?><ownershipDocument><documentType>4</documentType>
        <issuer><issuerCik>0000320193</issuerCik></issuer>
        <reportingOwner><reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>{role}</reportingOwnerRelationship></reportingOwner>
        <aff10b5One>{'true' if plan_box else 'false'}</aff10b5One>
        <nonDerivativeTable>{trades}</nonDerivativeTable><derivativeTable>{options}</derivativeTable>
        <footnotes><footnote id="F1">{footnote}</footnote><footnote id="F2">Price not reported.</footnote></footnotes>
        </ownershipDocument>""".encode()


DIRECTOR = "<isDirector>1</isDirector>"
CFO = "<isOfficer>true</isOfficer><officerTitle>Chief Financial Officer</officerTitle>"
# accession, form, filed, accepted (UTC), xml
FILINGS = [
    ("0000000001-26-000001", "4", "2026-10-02", "2026-10-02T21:00:00", form4("Doe Jane", DIRECTOR, [
        ("2026-09-30", "P", 1000, "100.00", False), ("2026-09-30", "F", 50, "100.00", False)])),
    ("0000000001-26-000002", "4", "2026-08-03", "2026-08-03T21:00:00", form4("Roe Rick", CFO, [
        ("2026-07-31", "S", 2000, "110.50", True), ("2026-07-31", "M", 2000, "20.00", False)], derivative=("M",))),
    ("0000000001-26-000003", "4", "2026-06-01", "2026-06-01T21:00:00", form4("Roe Rick", CFO, [
        ("2026-05-29", "S", 500, "105.00", False), ("2026-05-29", "G", 100, None, False)], plan_box=True)),
    ("0000000001-26-000004", "4", "2026-04-01", "2026-04-01T21:00:00", form4("Late Larry", DIRECTOR, [
        ("2025-01-15", "P", 10, "50.00", False)])),  # filed late: its trade is before the window
    ("0000000001-26-000005", "4", "2026-03-02", "2026-03-02T21:00:00", form4("Doe Jane", DIRECTOR, [
        ("2026-02-27", "P", 300, None, False)])),  # no price reported
    ("0000000001-26-000006", "4/A", "2026-08-10", "2026-08-10T21:00:00", form4("Roe Rick", CFO, [
        ("2026-07-31", "S", 2000, "110.50", True)])),
    ("0000000001-26-000007", "4", "2026-11-07", "2026-11-07T14:00:00", form4("Doe Jane", DIRECTOR, [
        ("2026-11-05", "P", 5000, "90.00", False)])),  # accepted after the cutoff
]


def sec_files(forms=("10-K",), filings=FILINGS):
    submissions = json.loads((FIXTURES / "submissions_AAPL.json").read_text())
    rows = [("0000320193-25-000079", form, "2025-10-31", "2025-10-31T20:00:00", None) for form in forms] + filings
    submissions["filings"] = {"files": [], "recent": {
        "accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows], "filingDate": [r[2] for r in rows],
        "acceptanceDateTime": [r[3] + ".000Z" for r in rows], "reportDate": [""] * len(rows),
        "items": [""] * len(rows), "primaryDocument": [("xslF345X06/form4.xml" if r[4] else "a.htm") for r in rows],
        "primaryDocDescription": [""] * len(rows)}}
    overrides = {"/submissions/CIK0000320193.json": httpx.Response(200, json=submissions)}
    overrides |= {FOLDER.format(r[0].replace("-", "")): httpx.Response(200, content=r[4]) for r in filings}
    return SecFiles(overrides)


def get(tmp_path, files=None, **args):
    files = files or sec_files()
    context = make_context(tmp_path, cutoff=CUTOFF, files=files)
    return run(GetInsiderTradesInput(cik="320193", **args), context), context, files


def test_only_purchases_and_sales_count_and_planned_sales_are_flagged(tmp_path):
    result, context, _ = get(tmp_path)
    assert result.status == "ok" and result.source == "SEC Form 4"
    trades = result.data["trades"]
    assert [(t["date"], t["code"], t["owner"]) for t in trades] == [
        ("2026-09-30", "P", "Doe Jane"), ("2026-07-31", "S", "Roe Rick"), ("2026-05-29", "S", "Roe Rick"),
        ("2026-02-27", "P", "Doe Jane")]
    # One sale's footnote names its 10b5-1 plan; the other is on a form whose 10b5-1 box is ticked.
    sales = [context.records[t["id"]] for t in trades if t["code"] == "S"]
    assert [(s["plan_10b5_1"], s["plan_basis"]) for s in sales] == [(True, "footnote"), (True, "form's 10b5-1 box")]
    totals = {name: Decimal(t["value"]) for name, t in result.data["totals"].items()}
    assert totals == {"insider_purchases": 100000, "insider_sales": 2000 * Decimal("110.50") + 500 * 105,
                      "insider_sales_planned": 2000 * Decimal("110.50") + 500 * 105,
                      "insider_net_purchases": 100000 - 2000 * Decimal("110.50") - 500 * 105, "insider_buyers": 1}
    assert result.data["not_counted"] == {"F": {"meaning": "shares withheld for tax", "transactions": 1},
                                          "G": {"meaning": "gift", "transactions": 1},
                                          "M": {"meaning": "option exercise", "transactions": 1},
                                          "M (derivative)": {"meaning": "option exercise", "transactions": 1}}
    assert any("1 trade(s) report no price" in w for w in result.warnings)


def test_window_amendments_and_the_cutoff_are_respected(tmp_path):
    result, context, files = get(tmp_path)
    dates = {t["date"] for t in result.data["trades"]}
    assert "2025-01-15" not in dates and "2026-11-05" not in dates  # before the window; public after the cutoff
    assert any("1 amendment(s) (4/A) not read: 0000000001-26-000006" in w for w in result.warnings)
    assert FOLDER.format("000000000126000006") not in files.paths
    assert result.data["filings_read"] == 5 and (result.data["start"], result.data["end"]) == ("2025-11-06", "2026-11-06")
    narrow, _, _ = get(tmp_path / "narrow", since=date(2026, 7, 1))
    assert [t["date"] for t in narrow.data["trades"]] == ["2026-09-30", "2026-07-31"]


def test_totals_are_facts_that_link_their_trades(tmp_path):
    result, context, _ = get(tmp_path)
    fact = context.records[result.data["totals"]["insider_sales"]["id"]]
    assert (fact["kind"], fact["unit"], fact["cik"], fact["start"], fact["end"]) == \
        ("fact", "USD", "0000320193", "2025-11-06", "2026-11-06")
    assert len(fact["trades"]) == 2 and all(context.records[i]["code"] == "S" for i in fact["trades"])
    shown = detail(fact, context.records)
    assert shown["excerpt"] == "$273,500" and len(shown["links"]) == 2
    trade = context.records[fact["trades"][0]]
    assert "Roe Rick (Chief Financial Officer): sale of 2000 shares at 110.50 on 2026-07-31, under a 10b5-1 plan" \
        in describe(trade)
    assert detail(trade, context.records)["title"] == "Insider sale by Roe Rick, 2026-07-31"


def test_a_footnote_saying_no_plan_wins_over_the_form_box(tmp_path):
    xml = form4("Roe Rick", CFO, [("2026-05-29", "S", 500, "105.00", True)], plan_box=True,
                footnote="This sale was not made pursuant to a Rule 10b5-1 trading plan.")
    result, context, _ = get(tmp_path, files=sec_files(filings=[("0000000001-26-000009", "4", "2026-06-01",
                                                                  "2026-06-01T21:00:00", xml)]))
    (trade,) = result.data["trades"]
    assert trade["plan_10b5_1"] is False and result.data["totals"]["insider_sales_planned"]["value"] == "0"


def test_a_foreign_filer_files_no_form_4_so_it_is_unsupported(tmp_path):
    result, _, _ = get(tmp_path, files=sec_files(forms=("20-F",), filings=[]))
    assert result.status == "unsupported" and "Section 16" in result.warnings[0]


def test_each_form_4_is_downloaded_once(tmp_path):
    files = sec_files()
    get(tmp_path, files=files)
    get(tmp_path, files=files)
    downloads = [p for p in files.paths if p.endswith("form4.xml")]
    assert len(downloads) == len(set(downloads)) == 5


def test_discover_can_check_insider_buying(tmp_path):
    context = make_context(tmp_path, cutoff=CUTOFF, files=sec_files())
    verdict = Acceptance(context, Trace.new(tmp_path / "traces")).check(
        "0000320193", ["AAPL"], [PriceCheck(metric="insider_buyers", op=">=", value=1),
                                 PriceCheck(metric="insider_net_purchases", op=">", value=0)])
    buyers, net = verdict.lines
    assert buyers.state == "pass" and buyers.text == "insider buyers >= 1 insider: 1 insider (2025-11-06 to 2026-11-06)"
    assert net.state == "fail" and verdict.state == "fail"
    assert context.records[net.ids[0]]["metric"] == "insider_net_purchases"


def test_status_page_lists_form_4_under_insider_trades():
    insiders = {k["kind"]: k for k in providers.status({})}["insiders"]
    (form4_provider,) = insiders["providers"]
    assert (form4_provider["name"], form4_provider["missing_env"]) == ("sec_form4", ["SEC_USER_AGENT"])


def test_the_spec_says_insider_checks_use_form_4s_not_the_close():
    from research_assistant.agents.discover_report import spec_lines
    from research_assistant.agents.discover_spec import ScreenSpec
    from research_assistant.data.universe import Member, Universe
    spec = ScreenSpec(rank_by="revenue", price_checks=[PriceCheck(metric="pe", op="<", value=30),
                                                       PriceCheck(metric="insider_buyers", op=">=", value=1)])
    universe = Universe("your list", "tickers", "2026-11-06", "", (Member("AAPL", "0000320193", "Apple Inc."),))
    line = next(t for t in spec_lines(spec, {}, universe, 3, "B") if t.startswith("Checked again"))
    assert line == ("Checked again on each candidate's latest 10-K before its research, with its latest close: pe < "
                    "30.0x, with its last year of Form 4 insider trades: insider buyers >= 1 insider.")
