"""Rebuild the trimmed real SEC fixtures (needs SEC_USER_AGENT and the network).

Run by hand: .venv/Scripts/python.exe tests/fixtures/build_sec_fixtures.py
tests/fixtures/sec/ is cut from live SEC responses. tests/fixtures/msft-fy2024/ is cut from the local-only
48 MB packet in verification/packets/ and is skipped when that packet is missing. Each file keeps the
original structure but only the parts the tests read.
"""
import json
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "sec"
load_dotenv(ROOT / ".env", override=False, interpolate=False, encoding="utf-8-sig")

from research_assistant.data.companies import ALL_NAMES_URL, TICKERS_URL  # noqa: E402
from research_assistant.data.sec import SecClient  # noqa: E402

CIKS = {"AAPL": 320193, "JPM": 19617, "TSM": 1046179, "BABA": 1577552, "CHKP": 1015922}
TICKERS = {"AAPL", "MSFT", "GOOG", "GOOGL", "JPM", "TSM", "BRK-B", "APLE", "NVDA"}
NAMES = ("APPLE INC:", "LEHMAN BROTHERS HOLDINGS INC:")
CONCEPTS = {"dei": ["EntityCommonStockSharesOutstanding"],
            "us-gaap": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenuesNetOfInterestExpense",
                        "OperatingIncomeLoss", "NetIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
                        "PaymentsToAcquirePropertyPlantAndEquipment", "Assets", "StockholdersEquity",
                        "EarningsPerShareDiluted", "CommonStockSharesOutstanding"],
            "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers", "ProfitLoss",
                          "ProfitLossAttributableToOwnersOfParent", "CashFlowsFromUsedInOperatingActivities",
                          "DilutedEarningsLossPerShare", "Assets", "LongtermBorrowings"]}
FRAMES = [("RevenueFromContractWithCustomerExcludingAssessedTax", 2024), ("RevenueFromContractWithCustomerExcludingAssessedTax", 2023),
          ("Revenues", 2024), ("Revenues", 2023), ("OperatingIncomeLoss", 2024), ("NetIncomeLoss", 2024)]
FRAME_CIKS = {320193, 19617, 789019, 1045810, 1652044}
FILING = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
KEEP_FACTS = ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:OperatingIncomeLoss")
XHTML, IX = "http://www.w3.org/1999/xhtml", "http://www.xbrl.org/2013/inlineXBRL"
# 20-F covers: BABA's ADS of eight ordinary shares (and its cut-off share-count tag), Check Point's direct listing,
# TSMC's "Common Shares" with the passages that say they trade as ADSs of five (its cover footnote and Item 6), and the
# statement rows of a few FY2025 facts companyfacts lacks (its NET REVENUE row uses the IFRS 15 tag). Each passage is
# (headings written before it, phrase).
COVERS = {"https://www.sec.gov/Archives/edgar/data/1577552/000119312526231755/baba-20260331.htm": ((), ()),
          "https://www.sec.gov/Archives/edgar/data/1015922/000117891326001932/zk2634942.htm": ((), ()),
          "https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm": ((
              ((), "Not for trading, but only in connection with the listing on the New York Stock Exchange, Inc. of "
                   "American Depositary Shares"),
              (("PART I", "ITEM 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES"),
               "shares held in the form of ADSs (each ADS represents five (5) common shares)")), (
              "ifrs-full:RevenueFromContractsWithCustomers", "ifrs-full:ProfitLossAttributableToOwnersOfParent",
              "ifrs-full:DilutedEarningsLossPerShare", "ifrs-full:Assets"))}
XBRLI = "http://www.xbrl.org/2003/instance"
COVER_END = re.compile(r"registrant\s+is\s+a\s+shell\s+company", re.I)


def write(name, payload):
    text = json.dumps(payload, indent=1) if not isinstance(payload, str) else payload
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"{name}: {len(text):,} chars")


def trim_facts(facts):
    out = {}
    for taxonomy, names in CONCEPTS.items():
        for name in names:
            concept = facts.get(taxonomy, {}).get(name)
            if not concept:
                continue
            units = {}
            for unit, rows in concept["units"].items():
                annual = [r for r in rows if r["form"] in ("10-K", "20-F") and r["filed"] >= "2024-10-01"]
                quarterly = [r for r in rows if r["form"] == "10-Q"][-1:]
                if annual or quarterly:
                    units[unit] = annual + quarterly
            if units:
                out.setdefault(taxonomy, {})[name] = {"label": concept.get("label"), "units": units}
    return out


def trim_filing(raw: bytes) -> str:
    """The real AAPL 10-K cut to: the TOC, each item's heading and first two paragraphs, the income
    statement and the XBRL contexts and units it uses. Styles are dropped; nothing else is rewritten."""
    from lxml import etree

    root = etree.fromstring(raw, etree.XMLParser(huge_tree=True))
    body = root.find(f"{{{XHTML}}}body")
    children = list(body)
    targets = set(re.findall(rb'href="#([^"]+)"', raw))
    toc = next(i for i, child in enumerate(children) if b'href="#' in etree.tostring(child))
    keep = set(range(1, toc + 1))
    for i, child in enumerate(children):
        if any(e.get("id", "").encode() in targets for e in child.iter() if isinstance(e.tag, str)):
            # The anchor, any page break after it, then the heading and two paragraphs with text.
            keep.add(i)
            texts, j = 0, i + 1
            while texts < 3 and j < len(children):
                keep.add(j)
                texts += bool("".join(children[j].itertext()).strip())
                j += 1
    statement = next(i for i, child in enumerate(children)
                     if etree.tostring(child).count(b"us-gaap:OperatingIncomeLoss") and b"Total net sales" in etree.tostring(child))
    keep.add(statement)
    used = set(re.findall(rb'contextRef="([^"]+)"', etree.tostring(children[statement])))
    header = children[0]
    for hidden in header.iter(f"{{{IX}}}hidden"):
        hidden.getparent().remove(hidden)
    for context in list(header.iter("{http://www.xbrl.org/2003/instance}context")):
        if context.get("id").encode() not in used:
            context.getparent().remove(context)
    for i, child in reversed(list(enumerate(children))):
        if i and i not in keep:
            body.remove(child)
    for element in root.iter():
        if isinstance(element.tag, str):
            element.attrib.pop("style", None)
    return etree.tostring(root, encoding="unicode")


def trim_cover(raw: bytes, keep: tuple = (), facts: tuple[str, ...] = ()) -> str:
    """A 20-F cut to its cover: everything up to the shell-company question that ends it, and the XBRL contexts and
    units the cover's tags use. Hidden facts, scripts and styles are dropped; the cover's tags and text stay as filed.
    The innermost paragraph, div or cell holding each `keep` phrase is copied after the cover, after its headings
    (so the cover ends where the filing's does), and so is the first table row tagging each of `facts` for the whole
    company (no dimensions), inside one table."""
    import copy

    from lxml import etree

    root = etree.fromstring(raw, etree.XMLParser(huge_tree=True))
    header = next(root.iter(f"{{{IX}}}header"))
    for element in [*header.iter(f"{{{IX}}}hidden"), *root.iter(f"{{{XHTML}}}script")]:
        element.getparent().remove(element)
    blocks = {f"{{{XHTML}}}{tag}" for tag in ("p", "div", "td")}
    extra = []
    for headings, phrase in keep:
        for text in headings:
            heading = etree.SubElement(etree.Element(f"{{{XHTML}}}div"), f"{{{XHTML}}}span")
            heading.text = text
            extra.append(heading.getparent())
        extra.append(copy.deepcopy([e for e in root.iter(*blocks) if phrase in " ".join("".join(e.itertext()).split())][-1]))
    whole = {c.get("id") for c in header.iter(f"{{{XBRLI}}}context") if c.find(f".//{{{XBRLI}}}segment") is None}
    if facts:
        table = etree.Element(f"{{{XHTML}}}table")
        for name in facts:
            table.append(copy.deepcopy(next(row for node in root.iter(f"{{{IX}}}nonFraction")
                                            if node.get("name") == name and node.get("contextRef") in whole
                                            for row in node.iterancestors(f"{{{XHTML}}}tr"))))
        extra.append(table)
    node = [e for e in root.iter() if isinstance(e.tag, str) and COVER_END.search(" ".join("".join(e.itertext()).split()))][-1]
    while node.tag != f"{{{XHTML}}}body":
        for sibling in list(node.itersiblings()):
            node.getparent().remove(sibling)
        node = node.getparent()
    node.extend(extra)
    used = set(re.findall(rb'(?:contextRef|unitRef)="([^"]+)"', etree.tostring(root)))
    for element in [*header.iter("{http://www.xbrl.org/2003/instance}context"), *header.iter("{http://www.xbrl.org/2003/instance}unit")]:
        if element.get("id").encode() not in used:
            element.getparent().remove(element)
    for element in root.iter():
        if isinstance(element.tag, str):
            element.attrib.pop("style", None)
    return etree.tostring(root, encoding="unicode")


PACKET = ROOT / "verification/packets/msft-fy2024/20261029T182734Z/raw"
PACKET_OUT = Path(__file__).resolve().parent / "msft-fy2024" / "raw"
PACKET_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "OperatingIncomeLoss")
BASIS_TEXT = (b"consolidated financial statements", b"accounting principles generally accepted in the United States",
              b"U.S. generally accepted accounting principles")


def trim_packet_filing(raw: bytes) -> bytes:
    """Keep the hidden cover facts, the income statement and the GAAP/consolidation wording the old parser
    checks; drop every other block and the contexts nothing uses. Bytes inside kept blocks are unchanged."""
    from lxml import etree

    root = etree.fromstring(raw, etree.XMLParser(huge_tree=True))
    body = root.find(f"{{{XHTML}}}body")
    children = list(body)
    blobs = [etree.tostring(child) for child in children]
    keep = {0} | {i for i, blob in enumerate(blobs) if b"dei:" in blob}
    keep.add(next(i for i, blob in enumerate(blobs) if b"us-gaap:OperatingIncomeLoss" in blob and b"Total revenue" in blob))
    for phrase in BASIS_TEXT:
        keep |= {next((i for i, blob in enumerate(blobs) if phrase.lower() in blob.lower() and i not in (0,)), 0)}
    for hidden in children[0].iter(f"{{{IX}}}hidden"):
        for fact in list(hidden):
            if not fact.get("name", "").startswith("dei:"):
                hidden.remove(fact)
    blobs[0] = etree.tostring(children[0])
    used = {ref for i in keep for ref in re.findall(rb'contextRef="([^"]+)"', blobs[i])}
    for context in list(children[0].iter("{http://www.xbrl.org/2003/instance}context")):
        if context.get("id").encode() not in used:
            context.getparent().remove(context)
    for i, child in reversed(list(enumerate(children))):
        if i not in keep:
            body.remove(child)
    for element in root.iter():
        if isinstance(element.tag, str):
            element.attrib.pop("style", None)
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def trim_packet():
    if not PACKET.is_dir():
        print("verification/packets/ is missing; msft-fy2024 fixtures left as they are.")
        return
    PACKET_OUT.mkdir(parents=True, exist_ok=True)
    facts = json.loads((PACKET / "companyfacts.json").read_bytes())
    gaap = facts["facts"]["us-gaap"]
    facts["facts"] = {"us-gaap": {tag: {"label": gaap[tag].get("label"), "units": {"USD": [
        row for row in gaap[tag]["units"]["USD"] if row["form"] in ("10-K", "10-K/A") and "2023" <= row["filed"] <= "2025"]}}
        for tag in PACKET_TAGS if tag in gaap}}
    (PACKET_OUT / "companyfacts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    (PACKET_OUT / "sec-index.html").write_bytes((PACKET / "sec-index.html").read_bytes())
    for name in ("sec-filing.html", "original-10k.html"):
        (PACKET_OUT / name).write_bytes(trim_packet_filing((PACKET / name).read_bytes()))
    for file in sorted(PACKET_OUT.iterdir()):
        print(f"msft-fy2024/raw/{file.name}: {file.stat().st_size:,} bytes")


def trim_submissions(payload):
    recent = payload["filings"]["recent"]
    forms = recent["form"]
    keep = []
    for wanted, count in (("10-K", 1), ("20-F", 1), ("10-Q", 2), ("8-K", 4), ("4", 1)):
        keep += [i for i, f in enumerate(forms) if f == wanted][:count]
    keep = sorted(set(keep))
    payload["filings"]["recent"] = {key: [values[i] for i in keep] for key, values in recent.items()}
    if int(payload["cik"]) != 320193:  # only Apple's older page is a fixture
        payload["filings"]["files"] = []
    for key in ("description", "addresses", "phone", "website", "investorWebsite", "ein", "lei", "flags"):
        payload.pop(key, None)
    return payload


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sec = SecClient()
    tickers = sec.get(TICKERS_URL).json()
    tickers["data"] = [row for row in tickers["data"] if row[2] in TICKERS]
    write("company_tickers_exchange.json", tickers)
    lines = sec.get(ALL_NAMES_URL).body.decode("latin-1").splitlines()
    write("cik-lookup-data.txt", "\n".join(line for line in lines if line.startswith(NAMES)) + "\n")
    for ticker, cik in CIKS.items():
        facts = sec.companyfacts(cik).json()
        write(f"companyfacts_{ticker}.json", {"cik": facts["cik"], "entityName": facts["entityName"], "facts": trim_facts(facts["facts"])})
        submissions = sec.submissions(cik).json()
        older = submissions["filings"]["files"][:1]
        write(f"submissions_{ticker}.json", trim_submissions(submissions))
        if older and ticker == "AAPL":
            page = sec.get(f"https://data.sec.gov/submissions/{older[0]['name']}").json()
            old_forms = page["form"]
            keep = ([i for i, f in enumerate(old_forms) if f == "10-K"][:1] + [i for i, f in enumerate(old_forms) if f == "8-K"][:2])
            write(older[0]["name"], {key: [values[i] for i in sorted(keep)] for key, values in page.items()})
    write("aapl-20250927.htm", trim_filing(sec.get(FILING).body))
    for url, (keep, facts) in COVERS.items():
        write(url.rsplit("/", 1)[-1], trim_cover(sec.get(url).body, keep, facts))
    for tag, year in FRAMES:
        frame = sec.get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json").json()
        frame["data"] = [row for row in frame["data"] if row["cik"] in FRAME_CIKS]
        write(f"frame_{tag}_CY{year}.json", frame)


if __name__ == "__main__":
    main()
    trim_packet()
