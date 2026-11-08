"""Companies by SIC industry code, from EDGAR's company search feed, and the sector ETF for a code (REFERENCE §10).

The feed lists every filer SEC files under a code, including ones that stopped filing long ago, so callers keep the
companies in today's ticker list. SIC is coarse and is today's code (Amazon is still SIC 5961, catalog retail).
"""
import xml.etree.ElementTree as ET

from .. import config
from .errors import DataError
from .sec import SecClient, cik10

FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic:04d}&owner=include&count=100"
        "&output=atom&start={start}")
PAGE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic:04d}&owner=include&count=100"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def members(sec: SecClient, sic: int) -> list[str]:
    """Every CIK SEC lists under one SIC code, one page of 100 at a time until the feed has no next page."""
    ciks, start = [], 0
    while True:
        try:
            root = ET.fromstring(sec.get(FEED.format(sic=sic, start=start)).body)
        except ET.ParseError as exc:
            raise DataError(f"SEC's company list for SIC {sic} is not a feed: {exc}", "bad_data") from exc
        page = [e.findtext("a:content/a:company-info/a:cik", namespaces=ATOM) for e in root.findall("a:entry", ATOM)]
        ciks += [cik10(c.strip()) for c in page if c and c.strip().isdigit()]
        if not page or root.find("a:link[@rel='next']", ATOM) is None:
            return list(dict.fromkeys(ciks))
        start += len(page)


def sector_etf(sic: int) -> dict | None:
    """The sector ETF config.SECTOR_ETFS maps a SIC code to, and the range that matched."""
    for low, high, ticker, sector in config.SECTOR_ETFS:
        if low <= sic <= high:
            return {"ticker": ticker, "sector": sector, "rule": f"SIC {sic} is in {low:04d}-{high:04d}, mapped to "
                    f"{ticker} ({sector}); approximate, since SIC isn't the sector scheme the ETF uses (GICS)."}
    return None
