"""Prospective XNYS Outlook logging owned by the application host."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from . import config
from .data.sec import SecClient
from .data.universe import UniverseError, load
from .store import Store
from .tools.get_outlook import GetOutlookInput, run as get_outlook
from .tools.get_prices import GetPricesInput, run as get_prices
from .tools.result import ToolContext


class OutlookScheduler:
    def __init__(self, store: Store, root: Path):
        self.store = store
        self.root = root
        self.stop = Event()
        self.thread: Thread | None = None
        self._lock = Lock()
        self.calendar = xcals.get_calendar("XNYS")
        self.tz = ZoneInfo("America/New_York")

    def start(self):
        if not config.OUTLOOK_LIVE_LOG_ENABLED or self.thread is not None:
            return
        self.thread = Thread(target=self._loop, name="outlook-live-log", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def _loop(self):
        while not self.stop.wait(config.OUTLOOK_SCHEDULER_POLL_SECONDS):
            try:
                self.run_once()
            except Exception:
                # The scheduler never crashes the app; its next polling cycle retries.
                continue

    def _context(self, now: datetime) -> ToolContext:
        sec = SecClient(cache_dir=self.root / "sec_cache")
        return ToolContext(
            cutoff=now,
            sec=sec,
            cache_dir=self.root,
        )

    def run_once(self, now: datetime | None = None):
        """Issue one forecast set on each XNYS session in the pre-close window."""
        with self._lock:
            now = now or datetime.now(timezone.utc)
            local = now.astimezone(self.tz)
            if not self.calendar.is_session(local.date().isoformat()):
                return
            close_minutes = 16 * 60
            issue_minutes = close_minutes - config.OUTLOOK_LOG_BEFORE_CLOSE_MINUTES
            elapsed = local.hour * 60 + local.minute
            if elapsed < issue_minutes or elapsed >= close_minutes:
                return
            context = self._context(now)
            try:
                universe = load(config.OUTLOOK_LIVE_UNIVERSE)
            except (UniverseError, OSError):
                return
            previous = self.calendar.previous_session(local.date().isoformat()).date()
            for member in universe.members:
                result = get_outlook(GetOutlookInput(
                    ticker=member.ticker,
                    start=previous - timedelta(days=config.OUTLOOK_DEFAULT_LOOKBACK_DAYS),
                    end=previous,
                    horizons=[5, 20],
                ), context)
                if result.status != "ok":
                    continue
                for record_id in result.ids:
                    record = context.records[record_id]
                    horizon = record["inputs"]["horizon"]
                    payload = {
                        **record,
                        "universe": config.OUTLOOK_LIVE_UNIVERSE,
                        "universe_source": universe.source,
                        "universe_as_of": universe.as_of,
                        "anchor_date": local.date().isoformat(),
                        "anchor_status": "pending",
                        "horizon_sessions": horizon,
                    }
                    self.store.append_outlook_record(payload)
            self.resolve_outcomes(now)

    def resolve_outcomes(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        entries = self.store.outlook_log()
        context = self._context(now)
        for entry in entries:
            if entry.kind != "record":
                continue
            payload = entry.payload
            if payload.get("anchor_status") != "pending":
                continue
            try:
                anchor = date.fromisoformat(payload["anchor_date"])
                horizon = int(payload["horizon_sessions"])
                ticker = payload["ticker"]
            except (KeyError, TypeError, ValueError):
                continue
            sessions = list(self.calendar.sessions_in_range(
                anchor.isoformat(),
                (anchor + timedelta(days=30 + horizon * 2)).isoformat(),
            ))
            positions = [session.date() for session in sessions]
            if anchor not in positions:
                continue
            anchor_index = positions.index(anchor)
            if anchor_index + horizon >= len(positions):
                continue
            resolved = positions[anchor_index + horizon]
            local = now.astimezone(self.tz)
            close_known = (local.date() > resolved or
                           (local.date() == resolved and local.hour * 60 + local.minute >= 16 * 60 + 120))
            if not close_known:
                continue
            start = get_prices(GetPricesInput(ticker=ticker, start=anchor, end=resolved), context)
            bench = get_prices(GetPricesInput(ticker="SPY", start=anchor, end=resolved), context)
            if start.status != "ok" or bench.status != "ok":
                from .contracts import OutlookOutcome
                self.store.append_outlook_outcome(OutlookOutcome(
                    forecast_id=payload["id"],
                    resolved_at=now,
                    status="unresolved",
                    note="Stock or SPY prices were unavailable when this window ended.",
                ))
                continue
            stock = context.records[start.ids[0]]
            benchmark = context.records[bench.ids[0]]
            stock_rows = {row["date"]: row["adj_close"] for row in stock["rows"]}
            bench_rows = {row["date"]: row["adj_close"] for row in benchmark["rows"]}
            if anchor.isoformat() not in stock_rows or anchor.isoformat() not in bench_rows:
                from .contracts import OutlookOutcome
                self.store.append_outlook_outcome(OutlookOutcome(
                    forecast_id=payload["id"], resolved_at=now, status="missed",
                    note="The anchor close was missing or unmeasurable.",
                ))
                continue
            if resolved.isoformat() not in stock_rows or resolved.isoformat() not in bench_rows:
                from .contracts import OutlookOutcome
                self.store.append_outlook_outcome(OutlookOutcome(
                    forecast_id=payload["id"], resolved_at=now, status="missed",
                    note="The window-end close was missing or unmeasurable.",
                ))
                continue
            stock_actual = stock_rows[resolved.isoformat()] / stock_rows[anchor.isoformat()] - 1
            bench_actual = bench_rows[resolved.isoformat()] / bench_rows[anchor.isoformat()] - 1
            from .contracts import OutlookOutcome
            outcome = OutlookOutcome(
                forecast_id=payload["id"],
                resolved_at=now,
                status="resolved",
                actual=Decimal(str(stock_actual)),
                benchmark_actual=Decimal(str(bench_actual)),
            )
            self.store.append_outlook_outcome(outcome)
