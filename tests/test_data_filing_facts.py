import copy
import json
from dataclasses import replace
from datetime import date

import pytest
from sec_files import FIXTURES, make_context

from research_assistant.data import filing_facts
from research_assistant.data.errors import DataError
from research_assistant.data.sec_filings import Filing

TSM_2025 = Filing("0001046179", "0001628280-26-025362", "20-F", date(2026, 4, 16), None, date(2025, 12, 31), (),
                  "tsm-20251231.htm", "")


def test_a_filings_ixbrl_facts_join_companyfacts_without_changing_it(tmp_path):
    context = make_context(tmp_path)
    payload = json.loads((FIXTURES / "companyfacts_TSM.json").read_text())
    before = copy.deepcopy(payload)
    merged, added = filing_facts.merged(payload, context.sec, TSM_2025, context.cache("ixbrl_cache"))
    assert payload == before and added > 0
    rows = merged["facts"]["ifrs-full"]["RevenueFromContractsWithCustomers"]["units"]["TWD"]
    latest = [r for r in rows if r["end"] == "2025-12-31"]
    assert [(r["val"], r["accn"], r["form"], r["filed"]) for r in latest] == [
        ("3809054300000", "0001628280-26-025362", "20-F", "2026-04-16")]
    assert latest[0]["document"].endswith("/tsm-20251231.htm") and latest[0]["locator"].startswith("#")
    # companyfacts already has this filing's cover count, so the filing's copy isn't added twice.
    shares = merged["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    assert shares == before["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]


def test_a_filing_without_an_html_document_is_an_error_not_a_guess(tmp_path):
    context = make_context(tmp_path)
    with pytest.raises(DataError, match="not HTML"):
        filing_facts.merged({"facts": {}}, context.sec, replace(TSM_2025, primary_document="tsm-20251231.txt"),
                            context.cache("ixbrl_cache"))
