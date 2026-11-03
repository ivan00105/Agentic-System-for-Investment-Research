"""Every tunable in one place, each with the reason it exists (PROJECT_GUIDE §5).

Values that come from the environment are functions, so a .env loaded after import still applies.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    # Saved runs, snapshots and caches. RESEARCH_DATA_DIR moves them, e.g. to a bigger disk.
    return Path(os.getenv("RESEARCH_DATA_DIR", "").strip() or PROJECT_ROOT / "data")


# --- SEC EDGAR (https://www.sec.gov/about/developer-resources) ---------------------------

# SEC's fair-access maximum. One limiter is shared by every SEC request in this process.
SEC_MAX_REQUESTS_PER_SECOND = 10

# Retries for 429, 5xx and network errors, so one blip doesn't fail a tool call.
# Waits double from the backoff: 1 s, 2 s, 4 s.
SEC_RETRIES = 3
SEC_RETRY_BACKOFF_SECONDS = 1.0

# Seconds to wait for a connection or for the next bytes, not for the whole download,
# so large files keep streaming as long as data keeps arriving.
SEC_TIMEOUT_SECONDS = 30

# companyfacts, submissions and the ticker lists change whenever a company files. A day keeps
# today's view current without refetching on every run. Archived filings never change, so the
# cache keeps them forever.
SEC_CACHE_MAX_AGE_HOURS = 24

# Protects memory from a broken response. The largest companyfacts files are tens of MB, so this
# is generous. Going over it is an error naming this setting, never a silent truncation.
SEC_MAX_RESPONSE_BYTES = 200_000_000

# --- Other HTTP data providers (Tiingo, ...) ----------------------------------------------

# Same reasons as the SEC settings above: one blip must not fail a tool call.
HTTP_RETRIES = 3
HTTP_RETRY_BACKOFF_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 30

# --- Tools --------------------------------------------------------------------------------

# Name searches can match dozens of companies. More matches than this are counted in a warning,
# never dropped silently; the agent can retry with a ticker or CIK.
FIND_COMPANY_MAX_MATCHES = 10
# rapidfuzz WRatio score (0-100) a name must reach to count as a match. Below ~80 the matches
# are mostly unrelated companies that share one word.
FIND_COMPANY_MIN_SCORE = 80

# Fiscal years returned when the agent doesn't ask: enough for growth and trends. Older years are
# counted in a warning and the agent can ask for them.
FINANCIALS_DEFAULT_YEARS = 5

# Filings returned per list_filings call. More are counted in a warning; the agent narrows with
# `forms` or `since`, or pages with `before`.
LIST_FILINGS_MAX_RESULTS = 50

# read_filing_section returns whole paragraphs until this many characters (~15k tokens), then
# says where the next page starts. A paragraph is never cut.
SECTION_PAGE_CHARS = 60_000
# Lines shorter than this are headings; they are merged into the paragraph that follows.
SECTION_HEADING_MAX_CHARS = 200
# Keyword-search hits returned per query, best first. More are counted in a warning.
SECTION_SEARCH_MAX_CHUNKS = 15

# Screen candidates returned when the request doesn't say how many.
SCREEN_DEFAULT_TOP_K = 5
# A calendar year's SEC frame is used once this many days have passed after 31 December: large
# filers file their 10-K within 60-90 days, so earlier frames are mostly empty.
SCREEN_FRAME_LAG_DAYS = 100

# --- Prices -------------------------------------------------------------------------------

# Provider order, best first; PRICE_PROVIDERS in .env overrides it (e.g. "yfinance,tiingo").
# Tiingo has raw and adjusted prices but needs a free key; yfinance needs no key.
PRICE_PROVIDERS = ("tiingo", "yfinance")
# Adjusted prices change whenever a dividend or split happens, so cached series refresh daily.
PRICE_CACHE_MAX_AGE_HOURS = 24
# History fetched when the agent gives no start date: three years covers volatility, drawdown and beta.
PRICE_DEFAULT_LOOKBACK_DAYS = 3 * 365
# A day's close counts as known from this New York hour on: the close is 16:00 and end-of-day
# vendors publish final prices about two hours later.
PRICE_CLOSE_AVAILABLE_HOUR = 18
# Annualisation for volatility: US exchanges trade about 252 days a year.
TRADING_DAYS_PER_YEAR = 252

# --- Agents -------------------------------------------------------------------------------

# Model calls per agent run: a guard against infinite loops, not a quality cap (§5). A Check or
# Compare question needs roughly 8-20 calls. Reaching the guard asks the model once for its best
# report from what it has, marked "stopped at limit"; it never errors.
AGENT_MAX_STEPS = 30
# Condition B's self-review (REFERENCE §7): when the checker flags the draft, the flags go back to
# the model this many times so it can fix them. They share the step guard above.
AGENT_SELF_REVIEW_PASSES = 1
# Retries of an agent's model call on 429, 5xx and connection errors, with the SDK's own backoff
# (0.5 s doubling to 8 s, or the provider's Retry-After). The SDK default of 2 (about 4 s) did not
# outlast OpenRouter's upstream 429s in the 3 Nov 2026 live check; 6 waits about 25 s. Agents also
# let OpenRouter fall back to another host of the same model. Baseline A keeps the SDK default.
AGENT_MODEL_RETRIES = 6


def trace_dir() -> Path:
    # One append-only JSONL trace per run, written step by step so a crash still leaves the trace.
    return data_dir() / "traces"


# --- Report checker -----------------------------------------------------------------------

# Digits the model may type because they name something rather than state a figure: form types,
# Item numbers, years, dates, quarters, index names. Any other digit outside a {fact:ID}/{calc:ID}
# placeholder is flagged (never removed) as a number no tool result backs.
CHECKER_ALLOWED_NUMBER_PATTERNS = (
    r"\b(?:10-K|10-Q|8-K|20-F|40-F|6-K|S-1|DEF 14A)(?:/A)?s?\b",  # SEC form types, also plural (8-Ks)
    r"\bSIC (?:code )?\d{4}\b",  # industry codes
    r"\bItems? \d{1,2}[A-C]?(?:\.\d{2})?\b",  # Item 1A, Item 7, Item 2.02
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b",  # ISO dates (period ends)
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r" \d{1,2}(?:, (?:19|20)\d{2})?\b",  # September 27, 2025
    r"\bFY ?(?:19|20)?\d{2}\b",  # FY2025, FY25
    r"\b(?:19|20)\d{2}\b",  # calendar and fiscal years
    r"\bQ[1-4]\b|\b[1-4]Q\d{2}\b",  # quarters
    r"\bS&P 500\b",
)

# Decimals shown when the checker fills a placeholder: percentages, percentage points, multiples and
# amounts in millions/billions. One decimal is how equity research quotes them (45.6%, 28.4x);
# per-share amounts keep two, as filed. The exact value stays in the cited record.
REPORT_DECIMALS = 1
