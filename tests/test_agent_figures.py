from research_assistant.agents.figures import figures
from research_assistant.agents.sources import chip, detail, item

CIK = "0000000001"


def fact(metric, end, value, filed="2025-11-01", start=None):
    start = start or f"{int(end[:4]) - 1}{end[4:]}"
    return {"id": f"fact-{metric}-{end}-{filed}", "kind": "fact", "cik": CIK, "metric": metric, "unit": "USD",
            "value": value, "start": start, "end": end, "form": "10-K", "accession": "0000000001-25-000001",
            "filed": filed, "tag": f"us-gaap:{metric}"}


def calc(id, formula, value, unit, **inputs):
    return {"id": id, "kind": "calc", "cik": CIK, "formula": formula, "inputs": inputs, "value": value,
            "unit": unit, "start": "2024-01-01", "end": "2024-12-31", "notes": []}


REV = {end: fact("revenue", end, value) for end, value in
       (("2022-12-31", "80000000000"), ("2023-12-31", "90000000000"), ("2024-12-31", "100000000000"))}
OI = {end: fact("operating_income", end, value) for end, value in
      (("2023-12-31", "18000000000"), ("2024-12-31", "25000000000"))}
RESTATED = fact("revenue", "2023-12-31", "91000000000", filed="2026-02-01")
M24 = calc("calc-m24", "ratio", "0.25", "ratio", numerator=OI["2024-12-31"]["id"], denominator=REV["2024-12-31"]["id"])
M23 = calc("calc-m23", "ratio", "0.2", "ratio", numerator=OI["2023-12-31"]["id"], denominator=REV["2023-12-31"]["id"])
GROWTH = calc("calc-g", "growth", "0.111111", "ratio", current=REV["2024-12-31"]["id"], previous=REV["2023-12-31"]["id"])
PP = calc("calc-pp", "change_pp", "5", "pp", current="calc-m24", previous="calc-m23")
PRICES = {"id": "prices-1", "kind": "prices", "cik": CIK, "ticker": "ACME", "source": "yfinance",
          "start": "2024-12-30", "end": "2025-01-02", "rows": [
              {"date": "2024-12-30", "close": 20.0, "adj_close": 10.0}, {"date": "2024-12-31", "close": None, "adj_close": None},
              {"date": "2025-01-02", "close": 11.5, "adj_close": 11.5}]}  # a 2-for-1 split on 2024-12-31
LONG = {**PRICES, "id": "prices-long", "start": "1999-01-04", "rows": [{"date": "1999-01-04", "close": 1.0, "adj_close": 0.5},
                                                                       *PRICES["rows"]]}
COMPANY = {"id": f"company-{CIK}", "kind": "company", "cik": CIK, "name": "Acme Corp", "tickers": ["ACME"]}
RECORDS = {r["id"]: r for r in [*REV.values(), *OI.values(), RESTATED, M24, M23, GROWTH, PP, PRICES, LONG, COMPANY]}


def test_key_numbers_table_puts_each_figure_with_its_period_and_change():
    cited = [REV["2024-12-31"]["id"], "calc-m24", "calc-pp", "prices-1"]
    rows = figures(cited, cited, RECORDS)["table"]
    assert [(r["metric"], r["period"], r["value"], r["change"]) for r in rows] == [
        ("Revenue", "year ended 2024-12-31", "$100.0 billion", "11.1%"),  # a growth calc the run made, not cited
        ("Operating margin", "year ended 2024-12-31", "25.0%", "+5.0 pp")]
    assert rows[0]["company"] == "Acme Corp" and rows[1]["change_id"] == "calc-pp"


def test_charts_show_every_frozen_year_and_a_refiled_year_uses_the_later_filing():
    [chart] = figures([REV["2024-12-31"]["id"], "prices-1"], [], RECORDS)["charts"]
    assert [(p["end"], p["label"]) for p in chart["revenue"]] == [
        ("2022-12-31", "$80.0 billion"), ("2023-12-31", "$91.0 billion"), ("2024-12-31", "$100.0 billion")]
    assert chart["margin"]["label"] == "Operating margin"
    assert [(p["end"], p["label"]) for p in chart["margin"]["points"]] == [("2023-12-31", "19.8%"),
                                                                           ("2024-12-31", "25.0%")]
    # The cited series, on adjusted closes, so the split is no drop; a blank close has no point.
    assert chart["price"]["id"] == "prices-1" and chart["price"]["points"] == [["2024-12-30", 10.0], ["2025-01-02", 11.5]]
    assert figures([REV["2024-12-31"]["id"]], [], RECORDS)["charts"][0]["price"]["id"] == "prices-long"  # none cited


def test_chips_and_the_evidence_panel_name_records_in_words():
    assert (item("part_i_item_1a"), item("part_ii_item_7"), item("item_202")) == ("Item 1A", "Item 7", "Item 2.02")
    records = {**RECORDS, "filing-0000000001-25-000001": {"id": "filing-0000000001-25-000001", "kind": "filing",
                                                          "form": "10-K", "filed": "2025-02-01"},
               "chunk-1": {"id": "chunk-1", "kind": "chunk", "form": "10-K", "accession": "0000000001-25-000001",
                           "section": "part_i_item_1a", "n": 4, "text": "Demand may fall."},
               "claim-1": {"id": "claim-1", "kind": "claim", "author": "filings", "version": 2,
                           "text": "Management says demand may fall.", "citations": ["chunk-1"]}}
    assert chip(records["chunk-1"], records) == "10-K 2025 Item 1A ¶4"
    assert chip(GROWTH, records) == "Revenue growth 2024"
    margin = detail(M24, records)
    assert margin["title"] == "Operating margin, year ended 2024-12-31" and margin["excerpt"] == "25.0%"
    assert [link["label"] for link in margin["links"]] == ["Operating income 2024", "Revenue 2024"]
    finding = detail(records["claim-1"], records)
    assert finding["group"] == "Analyst findings" and finding["links"] == [{"id": "chunk-1",
                                                                            "label": "10-K 2025 Item 1A ¶4"}]
    assert detail(PRICES, records)["excerpt"] == "2 trading days. Last close 11.50 on 2025-01-02 (as traded)."


def test_the_raw_table_lists_each_cited_figure_and_every_input_behind_it():
    from research_assistant.agents.figures import raw
    rows = raw(["calc-pp", "prices-1", "company-" + CIK], RECORDS)
    assert [r["id"] for r in rows] == ["calc-pp", "calc-m24", "calc-m23", OI["2024-12-31"]["id"],
                                       REV["2024-12-31"]["id"], OI["2023-12-31"]["id"], REV["2023-12-31"]["id"]]
    pp, m24 = rows[0], rows[1]
    assert pp["formula"] == "change_pp" and pp["inputs"] == {"current": "calc-m24", "previous": "calc-m23"}
    assert (pp["value"], pp["unit"], pp["company"]) == ("5", "pp", "Acme Corp")
    assert m24["shown"] == "25.0%" and m24["inputs"]["numerator"] == OI["2024-12-31"]["id"]
    revenue = rows[4]
    assert (revenue["value"], revenue["tag"], revenue["form"]) == ("100000000000", "us-gaap:revenue", "10-K")
