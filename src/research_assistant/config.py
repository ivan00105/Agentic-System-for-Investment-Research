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
