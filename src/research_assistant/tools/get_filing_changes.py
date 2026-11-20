"""Compatibility name for filing-change alerts."""
from .get_filing_change_alerts import GetFilingChangeAlertsInput, TOOL as _ALERT_TOOL, run

TOOL = type(_ALERT_TOOL)(
    "get_filing_changes",
    _ALERT_TOOL.description,
    GetFilingChangeAlertsInput,
    run,
    _ALERT_TOOL.source,
)
