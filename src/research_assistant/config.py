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
# Companies the web page's search box lists as the user types. More are counted ("8 of 40 matches"), never
# dropped silently, and typing more narrows them.
COMPANY_SUGGEST_MAX = 8

# Fiscal years returned when the agent doesn't ask: enough for growth and trends. Older years are
# counted in a warning and the agent can ask for them.
FINANCIALS_DEFAULT_YEARS = 5
# A 20-F cover without inline XBRL names its ADS ratio in the Section 12(b) row, right after "American
# Depositary Shares"; a ratio further away than this belongs to another row, so it isn't used.
COVER_RATIO_WINDOW_CHARS = 300
# When the cover gives no ratio, a sentence in the filing can ("ADSs (each ADS represents five (5) common shares)",
# TSMC). It counts only if it names the ADS itself or this close after a mention, so an RSA's "each represents" doesn't.
FILING_RATIO_LOOKBACK_CHARS = 80

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
# A margin above 100% can't come from sales alone (gains, other income, or a partial revenue tag), so the
# screen and Discover's acceptance test flag it unknown instead of ranking or passing it.
SCREEN_MAX_MARGIN = 1.0
# 52/53-week fiscal years end a few days off the month end, so inputs ending within a week are the same year.
SCREEN_PERIOD_SLACK_DAYS = 7

# --- Prices -------------------------------------------------------------------------------

# Provider order, best first; PRICE_PROVIDERS in .env overrides it (e.g. "yfinance,tiingo").
# Tiingo has raw and adjusted prices but needs a free key; yfinance needs no key.
PRICE_PROVIDERS = ("tiingo", "yfinance")
# Adjusted prices change whenever a dividend or split happens, so cached series refresh daily.
PRICE_CACHE_MAX_AGE_HOURS = 24
# Yahoo can list the newest day with a blank close for hours after it closes (seen at 21:23 New York time on
# 2 Nov 2026), so a series ending that way is refetched after this long; 30 minutes covers one research run.
PRICE_CACHE_BLANK_CLOSE_MAX_AGE_MINUTES = 30
# History fetched when the agent gives no start date: three years covers volatility, drawdown and beta.
PRICE_DEFAULT_LOOKBACK_DAYS = 3 * 365
# A day's close counts as known from this New York hour on: the close is 16:00 and end-of-day
# vendors publish final prices about two hours later.
PRICE_CLOSE_AVAILABLE_HOUR = 18
# Annualisation for volatility: US exchanges trade about 252 days a year.
TRADING_DAYS_PER_YEAR = 252
# A Sharpe ratio's risk-free average must cover the price series' dates to within this many days on each end: the
# bond and stock markets close on different holidays, so their first and last days can differ a little.
RISK_FREE_WINDOW_SLACK_DAYS = 7
# A 20-F/40-F share count and ADS ratio are as of the annual filing; a price more than this many days after that
# filing gets a warning, since buybacks or a ratio change may have happened since.
SHARE_FILING_MAX_AGE_DAYS = 365

# --- Macro: risk-free rate, rates, inflation, release dates (REFERENCE §10) -----------------

# Provider order, best first; MACRO_PROVIDERS in .env overrides it. FRED (free key) has every series, ALFRED
# vintages and the release calendar; Treasury (no key) has the bill and Treasury yields only.
MACRO_PROVIDERS = ("fred", "treasury")
# Today's observations can still arrive later in the day, so data as of the latest known day refreshes after this.
# Data as of an earlier day never changes (a FRED vintage is frozen; Treasury doesn't revise past rates).
MACRO_CACHE_MAX_AGE_HOURS = 12
# History read to find each series' latest value: monthly series (CPI, unemployment) are published weeks after
# the month, so about 13 months always holds the latest one and a year-earlier value.
MACRO_LATEST_LOOKBACK_DAYS = 400
# Release dates listed after the cutoff when the agent doesn't ask: about a month covers the next CPI, jobs report
# and FOMC decision. The agent can ask for up to MACRO_MAX_HORIZON_DAYS (a year of calendar is plenty).
MACRO_RELEASE_HORIZON_DAYS = 30
MACRO_MAX_HORIZON_DAYS = 366
# The FRED releases counted as major (https://fred.stlouisfed.org/releases): CPI (10), Employment Situation (50),
# GDP (53), Personal Income and Outlays incl. PCE inflation (54), FOMC press release (101).
MACRO_RELEASES = (10, 50, 53, 54, 101)
# FRED's terms set no published number; 120 a minute per key is the commonly cited limit, and a 429 is retried.
FRED_MAX_REQUESTS_PER_MINUTE = 120

# --- Exchange rates: another currency into US dollars (REFERENCE §10) ------------------------

# Provider order, best first; FX_PROVIDERS in .env overrides it. FRED's H.10 rates (free key) include TWD; Frankfurter
# (ECB reference rates, no key) has about 30 currencies, including CNY and HKD but not TWD.
FX_PROVIDERS = ("fred", "frankfurter")
# A year's average needs rates within this many days of both ends of the year, and a year-end rate one within this
# many days before the date: markets close for holidays (Lunar New Year, Christmas) and FRED posts H.10 a week late.
FX_WINDOW_SLACK_DAYS = 10
# Rates for a period that ended this long ago are complete and cached for good; newer ones refresh after the max age.
FX_FINAL_AFTER_DAYS = 14
FX_CACHE_MAX_AGE_HOURS = 12

# --- Peers and sector benchmark -----------------------------------------------------------

# Peers returned when the agent doesn't ask: enough to set margins and returns side by side. The agent can ask for more.
PEERS_DEFAULT_COUNT = 5
# SIC code ranges -> the SPDR sector ETF used as the sector benchmark; the first range that holds the code wins, so
# narrow ranges come first. SIC isn't GICS, so this is approximate: Alphabet and Meta are SIC 7370 (computer
# services) but GICS communication services. Codes: https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list
SECTOR_ETFS = (
    (2830, 2836, "XLV", "Health care"),  # drugs
    (2840, 2844, "XLP", "Consumer staples"),  # soaps and cosmetics
    (2900, 2999, "XLE", "Energy"),  # petroleum refining
    (3570, 3579, "XLK", "Technology"),  # computers
    (3630, 3639, "XLY", "Consumer discretionary"),  # household appliances
    (3600, 3699, "XLK", "Technology"),  # electronic equipment and semiconductors
    (3710, 3716, "XLY", "Consumer discretionary"),  # motor vehicles
    (3750, 3751, "XLY", "Consumer discretionary"),  # motorcycles and bicycles
    (3840, 3851, "XLV", "Health care"),  # medical instruments and supplies
    (3800, 3899, "XLK", "Technology"),  # other instruments
    (4950, 4959, "XLI", "Industrials"),  # waste management
    (4900, 4999, "XLU", "Utilities"),
    (4800, 4899, "XLC", "Communication services"),
    (5122, 5122, "XLV", "Health care"),  # drug wholesale
    (5140, 5149, "XLP", "Consumer staples"),  # grocery wholesale
    (5300, 5499, "XLP", "Consumer staples"),  # general merchandise (Walmart, Costco, Target) and food stores
    (5912, 5912, "XLP", "Consumer staples"),  # drug stores
    (6500, 6553, "XLRE", "Real estate"),
    (6798, 6798, "XLRE", "Real estate"),  # REITs
    (7311, 7311, "XLC", "Communication services"),  # advertising
    (7370, 7379, "XLK", "Technology"),  # software and computer services
    (7810, 7829, "XLC", "Communication services"),  # motion pictures
    (8000, 8099, "XLV", "Health care"),  # health services
    (100, 999, "XLP", "Consumer staples"),  # agriculture
    (1000, 1099, "XLB", "Materials"),  # metal mining
    (1200, 1399, "XLE", "Energy"),  # coal, oil and gas
    (1400, 1499, "XLB", "Materials"),
    (1500, 1799, "XLI", "Industrials"),  # construction
    (2000, 2199, "XLP", "Consumer staples"),  # food and tobacco
    (2200, 2399, "XLY", "Consumer discretionary"),  # textiles and apparel
    (2500, 2599, "XLY", "Consumer discretionary"),  # furniture
    (2700, 2799, "XLC", "Communication services"),  # publishing
    (2400, 2899, "XLB", "Materials"),  # lumber, paper, chemicals
    (3100, 3199, "XLY", "Consumer discretionary"),  # leather
    (3000, 3399, "XLB", "Materials"),  # rubber, glass, metals
    (3400, 3799, "XLI", "Industrials"),  # machinery, aircraft, ships, rail
    (3900, 3999, "XLY", "Consumer discretionary"),
    (4000, 4799, "XLI", "Industrials"),  # transportation
    (5000, 5199, "XLI", "Industrials"),  # wholesale
    (5200, 5999, "XLY", "Consumer discretionary"),  # retail and restaurants
    (6000, 6799, "XLF", "Financials"),  # banks, insurers, brokers, holding companies
    (7300, 7399, "XLI", "Industrials"),  # business services
    (7000, 7999, "XLY", "Consumer discretionary"),  # hotels, personal services, amusement
    (8000, 8999, "XLI", "Industrials"),  # engineering and management services
)

# --- Insider trades (SEC Form 4) ----------------------------------------------------------

# Window read when the agent gives no start date: a year of Form 4s, the span insider-trading studies usually use
# (Lakonishok and Lee 2001 look 6-12 months ahead). The agent can ask for any other start.
INSIDER_LOOKBACK_DAYS = 365
# Form 4 XMLs downloaded at once. A large company files a few hundred a year; SEC's shared 10-per-second limiter
# still applies, so this only hides each request's latency.
INSIDER_FETCH_WORKERS = 8

# --- Agents -------------------------------------------------------------------------------

# Model calls per agent loop: a guard against infinite loops, not a quality cap (§5). It applies to the
# single agent, the coordinator, and each request the coordinator sends an analyst (PROJECT_GUIDE §5:
# about 30 per analyst). A Check or Compare question needs roughly 8-20 calls. Reaching the guard asks
# the model once for its best report or findings from what it has, marked "stopped at limit"; it never errors.
AGENT_MAX_STEPS = 30
# Condition B's self-review (REFERENCE §7): when the checker flags the draft, the flags go back to
# the model this many times so it can fix them. They share the step guard above.
AGENT_SELF_REVIEW_PASSES = 1
# Condition D's critic (REFERENCE §3): reviews of the report per run. After a review with a material objection the
# coordinator revises the report and the critic reviews it again; it stops sooner once no material objection has a
# feasible next action. A guard, not a target: more debate rounds can make results worse (Kaesberg et al. 2025).
# What the last review raises, and anything still open then, is shown as unresolved, never dropped.
AGENT_CRITIC_ROUNDS = 3
# Retries of an agent's model call on 429, 5xx and connection errors, with the SDK's own backoff
# (0.5 s doubling to 8 s, or the provider's Retry-After). The SDK default of 2 (about 4 s) did not
# outlast OpenRouter's upstream 429s in the 3 Nov 2026 live check; 6 waits about 25 s. Agents also
# let OpenRouter fall back to another host of the same model. Baseline A keeps the SDK default.
AGENT_MODEL_RETRIES = 6
# Retries of a model call whose 200 reply body isn't JSON (a host cut the reply off), which the SDK doesn't retry.
# Seen once in the 3 Nov 2026 live Discover check; after these the call fails like any other model error.
AGENT_BAD_REPLY_RETRIES = 2
# Decoding settings for agent calls. None sends nothing (the provider's default); run_start and the eval manifest
# record them either way, since a run can't be reproduced without them. A seed only works on hosts that support it.
AGENT_TEMPERATURE: float | None = None
AGENT_TOP_P: float | None = None
AGENT_SEED: int | None = None

# Discover (REFERENCE §4): companies explained when the question doesn't say how many. Each one is a full
# research run (B, C or D), so three keeps a Discover run to about the cost and time of three Check runs.
DISCOVER_DEFAULT_TOP_K = 3
# Research runs allowed beyond top-k, to replace candidates whose research failed (PROJECT_GUIDE §5: "top-k plus
# a few replacements", user-adjustable with --replacements). Candidates the deterministic check rejects cost no
# model call and don't count. On reaching it the shortlist returns fewer picks and says why.
DISCOVER_MAX_REPLACEMENTS = 3
# The research condition of a Discover run started from the web page, unless Advanced options pick another. Each pick
# is a full research run: B (one agent) keeps three picks to minutes and cents, while D takes about 20 minutes a pick.
WEB_DISCOVER_CONDITION = "B"
# Longest label a user can give a saved run in History: room for a sentence, short enough to stay one line in lists.
RUN_LABEL_MAX = 120

# Evaluation intervals (REFERENCE §7): resamples of cases for the 95% bootstrap interval, plenty for its two ends;
# the fixed seed makes a rescore of the same batch print the same intervals.
EVAL_BOOTSTRAP_RESAMPLES = 2000
EVAL_BOOTSTRAP_SEED = 7608


def trace_dir() -> Path:
    # One append-only JSONL trace per run, written step by step so a crash still leaves the trace.
    return data_dir() / "traces"


def eval_dir() -> Path:
    # Evaluation batches (eval/run_eval.py): one folder each, with its run index, traces and score tables. Kept apart
    # from traces/, so evaluation runs don't fill the web app's History.
    return data_dir() / "eval"


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
