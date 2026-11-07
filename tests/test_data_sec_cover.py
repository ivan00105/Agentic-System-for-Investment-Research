from datetime import date
from fractions import Fraction

import httpx
import pytest
from sec_files import FIXTURES, SecFiles, make_context

from research_assistant.data import sec_cover
from research_assistant.data.sec_filings import Filing
from research_assistant.filings import Document


@pytest.mark.parametrize("title, expected", [
    ("American Depositary Shares, each representing eight Ordinary Shares", Fraction(8)),
    ("American depositary shares, each representing two Class A ordinary shares, par value $0.0001 per share", Fraction(2)),
    ("American Depositary Shares (each representing 10 Ordinary Shares)", Fraction(10)),
    ("American Depositary Shares, each representing five (5) common shares", Fraction(5)),
    ("American Depositary Shares, each representing twenty-five ordinary shares", Fraction(25)),
    ("American Depositary Shares, each representing one hundred ordinary shares", Fraction(100)),
    ("American Depositary Shares, each representing one share", Fraction(1)),
    ("American Depositary Shares, each representing one-half of one ordinary share", Fraction(1, 2)),
    ("American Depositary Shares, each representing two-thirds of one ordinary share", Fraction(2, 3)),
    ("American Depositary Shares, each representing one-fourth of one Class A ordinary share", Fraction(1, 4)),
    ("American depositary shares each representing 0.5 of an ordinary share", Fraction(1, 2)),
    ("American Depositary Shares, each ADS represents 1/10 of one ordinary share", Fraction(1, 10)),
    ("ADSs, every two of which represent three ordinary shares", Fraction(3, 2)),
    ("American Depositary Shares", None),
    ("American Depositary Shares, each representing the right to receive eight ordinary shares", None),
    ("American Depositary Shares, each representing 1/0 of one ordinary share", None),
])
def test_ordinary_shares_per_ads_from_the_title(title, expected):
    assert sec_cover.ratio(title) == expected


def cover(body: str) -> dict:
    page = (f'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>Securities registered or to be registered '
            f'pursuant to Section 12(b) of the Act: {body} Securities registered or to be registered pursuant to '
            'Section 12(g) of the Act: None</body></html>')
    return sec_cover._read(Document(page.encode()))


def title(text: str) -> str:
    return f'<ix:nonNumeric name="dei:Security12bTitle" contextRef="c">{text}</ix:nonNumeric>'


def test_baba_cover_gives_eight_and_the_count_the_page_shows():
    found = sec_cover._read(Document((FIXTURES / "baba-20260331.htm").read_bytes()))
    assert found["ratio"] == "8/1" and found["how"] == "dei:Security12bTitle" and found["problem"] is None
    assert found["basis"] == "American Depositary Shares, each representing eight Ordinary Shares"
    # The tag holds "18,580,374,27"; the last digit is printed just after it.
    assert found["shares"] == [{"tagged": "18,580,374,27", "shown": "18,580,374,278"}]


def test_direct_listing_is_one_ordinary_share_per_listed_share():
    found = sec_cover._read(Document((FIXTURES / "zk2634942.htm").read_bytes()))
    assert found["ratio"] == "1/1" and found["how"] == "no depositary shares" and found["basis"] == "Ordinary shares"
    assert found["shares"] == [{"tagged": "105,596,035", "shown": None}]


def test_without_the_tag_the_cover_text_is_read():
    found = cover("Title of each class Ordinary shares* American Depositary Shares, each representing two ordinary "
                  "shares XYZ New York Stock Exchange")
    assert found["ratio"] == "2/1" and found["how"] == "cover text"
    assert found["basis"] == "American Depositary Shares, each representing two ordinary shares"


def test_a_listed_class_that_trades_as_ads_without_a_ratio_is_a_problem():
    # TSMC's cover tags only "Common Shares"; a footnote says they trade as ADSs, with no ratio.
    found = cover(title("Common Shares") + "* TSM New York Stock Exchange * Not for trading, but only in connection "
                  "with the listing of American Depositary Shares representing such Common Shares.")
    assert found["ratio"] is None and "mentions American depositary shares" in found["problem"]


def test_two_depositary_classes_or_an_unreadable_one_are_problems():
    two = cover(title("American Depositary Shares, each representing one Class A share")
                + title("American Depositary Shares, each representing ten Class B shares"))
    assert two["ratio"] is None and "more than one depositary class" in two["problem"]
    unreadable = cover(title("American Depositary Shares"))
    assert unreadable["ratio"] is None and "can't be read" in unreadable["problem"]


def test_a_cover_listing_only_notes_has_no_shares():
    found = cover(title("4.500% Notes due 2034"))
    assert found["ratio"] is None and "lists no shares" in found["problem"]


def test_a_cover_is_read_once_and_cached(tmp_path):
    context = make_context(tmp_path)
    filing = Filing("0001577552", "0001193125-26-231755", "20-F", date(2026, 5, 20), None, date(2026, 3, 31), (),
                    "baba-20260331.htm", "")
    first = sec_cover.read(context.sec, filing, context.cache("ixbrl_cache"))
    offline = SecFiles({"/Archives/edgar/data/1577552/000119312526231755/baba-20260331.htm": httpx.Response(500)})
    again = sec_cover.read(make_context(tmp_path / "other", files=offline).sec, filing, context.cache("ixbrl_cache"))
    assert first == again and first["ratio"] == "8/1" and offline.paths == []
