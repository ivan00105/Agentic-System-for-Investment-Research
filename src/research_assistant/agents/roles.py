"""The research roles (REFERENCE §2). Every role is the same loop (loop.py) with its own prompt and tools.

Add an analyst: write prompts/<name>.md and add a Role here and to ANALYSTS (PROJECT_GUIDE §8). Its tool list is
enforced: the loop refuses any other tool the model asks for.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str  # also the prompt file (prompts/<name>.md) and the role's tag in the trace
    tools: tuple[str, ...] | None  # registry tools it may run; None means every tool
    title: str = ""  # how the coordinator's tool list names an analyst
    brief: str = ""  # what the coordinator reads about an analyst when choosing whom to ask
    plan_prompt: str = "plan"  # the lead role's planning prompt


# Condition B: one agent with every tool.
SINGLE = Role("single_agent", None)

# Condition C. Every tool B has is with some role, so B and C differ in specialization, not in tools.
# Departures from REFERENCE §2, recorded there: every analyst can find_company; the market analyst also reads
# get_financials (market cap needs a share count, P/E needs earnings); fundamentals has verify_against_filing.
COORDINATOR = Role("coordinator", ("find_company", "calculate", "screen"), plan_prompt="coordinator_plan")
FUNDAMENTALS = Role("fundamentals", ("find_company", "get_financials", "calculate", "verify_against_filing"),
                    "fundamentals", "Reported figures from SEC filings, margins, growth, free cash flow, and whether "
                    "fiscal periods compare; can check a figure against the filing.")
FILINGS = Role("filings", ("find_company", "read_filing_section", "list_filings", "get_insider_trades"),
               "filings and events", "Reads 10-K sections (Item 1A risks, Item 7 management's discussion), recent 8-K "
               "events and insiders' Form 4 purchases and sales, and attributes management's claims.")
MARKET = Role("market", ("find_company", "get_prices", "get_financials", "calculate", "get_macro"),
              "market and valuation",
              "Price history, returns, volatility, drawdown, beta and Sharpe ratio, valuation (market cap, P/E, P/S, FCF "
              "yield), and rates, inflation and upcoming macro release dates as context.")
ANALYSTS = (FUNDAMENTALS, FILINGS, MARKET)

# Condition D. The critic reads; every tool it has only looks data up or recomputes it (REFERENCE §2: read-only tools
# plus verify_against_filing). screen is left out: it ranks companies, which a review of one report never needs.
CRITIC = Role("critic", ("find_company", "get_financials", "calculate", "verify_against_filing", "read_filing_section",
                         "list_filings", "get_prices", "get_macro", "get_insider_trades"), "critic")
