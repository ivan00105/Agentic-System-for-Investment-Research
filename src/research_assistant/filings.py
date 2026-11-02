"""Bounded SEC archival retrieval and the narrow Inline XBRL fields we support."""
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from zoneinfo import ZoneInfo

from .contracts import DomainError, FilingPacket, SourceDocument, UNIVERSE, utcnow

MAX_SOURCE_BYTES = 25_000_000
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")


def fetch_source(client, url, user_agent):
    # The application has one retrieval worker. Pace even cached/fast SEC replies
    # below EDGAR's ten-requests-per-second limit across all three source types.
    time.sleep(0.11)
    try:
        with client.stream("GET", url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise DomainError("SEC response exceeds the local retrieval limit.", "source_limit")
                chunks.append(chunk)
        return b"".join(chunks), utcnow()
    except httpx.HTTPError as exc:
        raise DomainError("SEC filing retrieval failed. Saved results remain available; retry explicitly later.", "retrieval_failed", 502) from exc


class Node:
    def __init__(self, tag="", attrs=None, parent=None, start=0):
        self.tag, self.attrs, self.parent, self.start = tag, dict(attrs or []), parent, start
        self.end = start
        self.children = []

    def nodes(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes(tag)

    def text(self):
        return " ".join("".join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def ancestor(self, tag):
        node = self.parent
        while node is not None and node.tag != tag:
            node = node.parent
        return node


class Document(HTMLParser):
    """Keep source positions; no scripts, URLs, entities or external resources execute."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        try:
            self.source = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DomainError("Filing character encoding is unsupported.", "source_format") from exc
        self.raw = raw
        self.lines = [0]
        for match in re.finditer("\n", self.source):
            self.lines.append(match.end())
        self.root = self.current = Node()
        try:
            self.feed(self.source)
            self.close()
        except (RecursionError, ValueError) as exc:
            raise DomainError("SEC returned an unsupported filing document.", "source_format") from exc

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current, self.position())
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None and node.tag != tag:
            node = node.parent
        if node.parent is not None:
            end = self.source.find(">", self.position()) + 1
            node.end = end
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)

    def fragment(self, node):
        if node.end <= node.start:
            raise DomainError("Filing table has no stable source locator.", "source_format")
        # Preserve the exact received bytes, including a possible UTF-8 BOM.
        offset = 3 if self.raw.startswith(b"\xef\xbb\xbf") else 0
        start = offset + len(self.source[:node.start].encode("utf-8"))
        end = offset + len(self.source[:node.end].encode("utf-8"))
        return self.raw[start:end], start, end


def retrieve_packet(store, ticker, annual, cutoff, client, user_agent):
    # Accession prefixes identify the submitter, not necessarily the issuer (e.g. MSFT).
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", annual.accn):
        raise DomainError("SEC returned an invalid accession.", "source_format")
    cik = UNIVERSE[ticker]["cik"]
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{annual.accn.replace('-', '')}/"
    index_url = base + annual.accn + "-index.htm"
    index_raw, index_at = fetch_source(client, index_url, user_agent)
    index = Document(index_raw)
    content = index.root.text()
    if not re.search(r"CIK\s*:\s*" + cik, content) or annual.accn not in content:
        raise DomainError("Filing index issuer/accession does not match the selected fact.", "issuer_mismatch")
    filed = re.search(r"Filing Date\s+(\d{4}-\d{2}-\d{2})", content)
    period = re.search(r"Period of Report\s+(\d{4}-\d{2}-\d{2})", content)
    if not filed or not period or date.fromisoformat(filed[1]) != annual.filed or date.fromisoformat(period[1]) != annual.end:
        raise DomainError("Filing dates do not match the selected annual fact.", "source_format")
    from .research import conservative_availability
    if conservative_availability(annual.filed) > cutoff:
        raise DomainError("Filing is later than the research cutoff.", "ineligible_evidence")
    links = []
    for row in index.root.nodes("tr"):
        cells = [c for c in row.children if isinstance(c, Node) and c.tag in {"td", "th"}]
        if len(cells) >= 4 and cells[3].text() == annual.form:
            links.extend(row.nodes("a"))
    if len(links) != 1:
        raise DomainError("A unique original annual filing document is unavailable.", "source_format")
    href = links[0].attrs.get("href", "")
    if href.startswith("/ix?doc="):
        href = parse_qs(urlsplit(href).query).get("doc", [""])[0]
    url = urljoin(index_url, href)
    filename = url.removeprefix(base)
    if not url.startswith(base) or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.html?", filename):
        raise DomainError("Filing document link is outside the selected SEC accession.", "source_format")
    raw, retrieved_at = fetch_source(client, url, user_agent)
    doc = Document(raw)
    identity = {n.attrs.get("name"): n.text() for n in doc.root.nodes("ix:nonnumeric")}
    if identity.get("dei:EntityCentralIndexKey", "").zfill(10) != cik:
        raise DomainError("Original filing issuer does not match the requested company.", "issuer_mismatch")
    if identity.get("dei:DocumentType") != annual.form:
        raise DomainError("Original filing form does not match the selected accession.", "source_format")
    try:
        displayed_end = identity.get("dei:DocumentPeriodEndDate", "")
        try:
            document_end = date.fromisoformat(displayed_end)
        except ValueError:
            document_end = datetime.strptime(re.sub(r",\s*", ", ", displayed_end), "%B %d, %Y").date()
        if document_end != annual.end or identity.get("dei:AmendmentFlag", "").lower() != str(annual.form == "10-K/A").lower():
            raise ValueError("Wrong document period/amendment")
    except ValueError as exc:
        raise DomainError("Original filing period/amendment does not match the selected accession.", "source_format") from exc
    documents = [SourceDocument(role=role, source_url=source_url, snapshot_hash=store.snapshot(body),
                                byte_length=len(body), media_type="text/html", retrieved_at=at)
                 for role, source_url, body, at in [("filing_index", index_url, index_raw, index_at), ("filing", url, raw, retrieved_at)]]
    acceptance = re.search(r"Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", content)
    accepted_at = datetime.strptime(acceptance[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc) if acceptance else None
    packet = FilingPacket(cik=cik, accession=annual.accn, form=annual.form, filed=annual.filed, period_end=annual.end, accepted_at=accepted_at, documents=documents)
    return packet, doc, url, retrieved_at
