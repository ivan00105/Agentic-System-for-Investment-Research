"""Discover's acceptance test (REFERENCE §4 rules 4, 6, 8): the screen used SEC frames (restated, calendar-aligned),
so before a candidate is researched the host checks every filter again on its latest 10-K (companyfacts, as of the
cutoff) and every price check on its latest close, by running the tools itself. No model is involved. Unknown never
passes, and each line cites the records it rests on."""
from dataclasses import dataclass, field
from decimal import Decimal

from ..tools import registry
from ..tools.result import ToolContext, ToolResult
from ..tools.screen import OPERATORS, implausible
from .checker import format_value
from .trace import Trace

# How each metric is computed: a calculate formula and the input behind each role. An input is another metric here,
# a get_financials metric for the latest fiscal year, "@prior" for the year before, or "prices" (the latest series).
PLANS = {
    "fcf": ("fcf", {"operating_cash_flow": "operating_cash_flow", "capex": "capex"}),
    "operating_margin": ("ratio", {"numerator": "operating_income", "denominator": "revenue"}),
    "net_margin": ("ratio", {"numerator": "net_income", "denominator": "revenue"}),
    "fcf_margin": ("ratio", {"numerator": "fcf", "denominator": "revenue"}),
    "revenue_growth": ("growth", {"current": "revenue", "previous": "revenue@prior"}),
    "market_cap": ("market_cap", {"prices": "prices", "shares": "shares_outstanding"}),
    "pe": ("pe", {"market_cap": "market_cap", "net_income": "net_income"}),
    "ps": ("ps", {"market_cap": "market_cap", "revenue": "revenue"}),
    "pb": ("pb", {"market_cap": "market_cap", "equity": "stockholders_equity"}),
    "fcf_yield": ("fcf_yield", {"fcf": "fcf", "market_cap": "market_cap"}),
    "volatility": ("volatility", {"prices": "prices"}),
    "max_drawdown": ("max_drawdown", {"prices": "prices"}),
}
UNITS = {"revenue": "USD", "operating_income": "USD", "net_income": "USD", "operating_cash_flow": "USD", "fcf": "USD",
         "market_cap": "USD", "pe": "x", "ps": "x", "pb": "x"}  # every other metric is a ratio


def threshold(metric: str, op: str, value: float) -> str:
    """A criterion in words, e.g. "operating margin > 25.0%"."""
    return f"{metric.replace('_', ' ')} {op} {format_value({'value': value, 'unit': UNITS.get(metric, 'ratio')})}"


@dataclass
class Line:
    state: str  # pass | fail | unknown
    text: str
    ids: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    state: str
    lines: list[Line]


class Unknown(Exception):
    """A metric that can't be computed; the message says why."""


class Acceptance:
    def __init__(self, context: ToolContext, trace: Trace):
        self.context, self.trace = context, trace

    def call(self, name: str, arguments: dict) -> ToolResult:
        """Run a tool as the host and trace it like an agent's call, so the trace freezes its records."""
        result = registry.call(name, arguments, self.context)
        self.trace.write("tool_call", step=None, name=name, arguments=arguments, repeat_of=None,
                         result=result.model_dump(mode="json"), records=self.trace.new_records(self.context.records))
        return result

    def check(self, cik: str, tickers: list[str], criteria: list) -> Verdict:
        """`criteria` are the spec's filters and price checks (metric, op, value)."""
        self.cik, self.tickers, self.done = cik, tickers, {}
        self.facts, self.reasons, self.ends, self.missing, self.currency = {}, {}, [], None, {}
        needed = sorted({leaf for c in criteria for leaf in _leaves(c.metric)} - {"prices"})
        if needed:
            result = self.call("get_financials", {"cik": cik, "metrics": needed, "years": 2})
            if result.status in ("ok", "partial"):
                self.ends = result.data["fiscal_year_ends"]
                self.facts = {name: m["values"] for name, m in result.data["metrics"].items() if m["status"] == "ok"}
                self.reasons = {name: m["reason"] for name, m in result.data["metrics"].items() if m.get("reason")}
                # USD figures next to another currency are probably convenience translations; each line says so.
                self.currency = {name: w for w in result.warnings for name in needed
                                 if w.startswith(f"{name} is also reported in ")}
            else:
                self.missing = f"get_financials came back {result.status}: {' '.join(result.warnings)}"
        lines = [self._line(c) for c in criteria]
        states = {line.state for line in lines}
        return Verdict("fail" if "fail" in states else "unknown" if "unknown" in states else "pass", lines)

    def _line(self, criterion) -> Line:
        rule = threshold(criterion.metric, criterion.op, criterion.value)
        try:
            record = self.context.records[self._resolve(criterion.metric)]
        except Unknown as exc:
            return Line("unknown", f"{rule}: unknown ({exc})")
        if record.get("value") is None:
            return Line("unknown", f"{rule}: unknown ({record.get('reason') or 'no value'})", [record["id"]])
        value = Decimal(str(record["value"]))
        if doubt := implausible(criterion.metric, value):  # as in the screen: unknown, but the record stays cited
            return Line("unknown", f"{rule}: unknown ({doubt})", [record["id"]])
        passed = OPERATORS[criterion.op](value, Decimal(str(criterion.value)))
        if record.get("formula") == "growth":  # its start is the earlier year's, so a span would read as two years
            period = f"fiscal year ending {record['end']} against the one before"
        elif record.get("start"):
            period = f"{record['start']} to {record['end']}"
        else:
            period = f"at {record.get('end')}"
        notes = [self.currency[leaf].rstrip(".") for leaf in sorted(_leaves(criterion.metric)) if leaf in self.currency]
        basis = f". Basis: USD as filed ({'; '.join(notes)})." if notes else ""
        return Line("pass" if passed else "fail", f"{rule}: {format_value(record)} ({period}){basis}", [record["id"]])

    def _resolve(self, name: str) -> str:
        """The record ID for a metric of this candidate, computing what it needs first."""
        if name in self.done:
            return self.done[name]
        if name == "prices":
            if not self.tickers:
                raise Unknown("no ticker to fetch prices for")
            result = self.call("get_prices", {"ticker": self.tickers[0]})
            if result.status != "ok":
                raise Unknown(f"get_prices came back {result.status}: {' '.join(result.warnings)}")
            found = result.ids[0]
        elif name in PLANS:
            formula, roles = PLANS[name]
            inputs = {role: self._resolve(source) for role, source in roles.items()}
            result = self.call("calculate", {"formula": formula, "inputs": inputs})
            if not result.ids:
                raise Unknown(f"calculate {formula} came back {result.status}: {' '.join(result.warnings)}")
            found = result.ids[0]
        else:
            found = self._fact(*name.split("@"))
        self.done[name] = found
        return found

    def _fact(self, metric: str, which: str = "latest") -> str:
        if self.missing:
            raise Unknown(self.missing)
        values = self.facts.get(metric)
        if not values:
            raise Unknown(f"{metric}: {self.reasons.get(metric, 'not reported')}")
        if metric == "shares_outstanding":  # a cover-page count: the latest one, whatever its date
            return max(values, key=lambda v: v["end"])["id"]
        index = 0 if which == "latest" else 1
        if len(self.ends) <= index:
            raise Unknown(f"no {'prior ' if index else ''}fiscal year before the cutoff")
        end = self.ends[index]
        found = next((v["id"] for v in values if v["end"] == end), None)
        if found is None:
            raise Unknown(f"{metric} not reported for the fiscal year ending {end}")
        return found


def _leaves(metric: str) -> set[str]:
    """The get_financials metrics (and "prices") a metric is computed from."""
    if metric not in PLANS:
        return {metric.split("@")[0]}
    return {leaf for source in PLANS[metric][1].values() for leaf in _leaves(source)}
