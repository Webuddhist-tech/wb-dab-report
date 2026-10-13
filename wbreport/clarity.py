"""Website figures from Microsoft Clarity's Data Export API. Standard library only.

The API covers a rolling window that ends when it's called (numOfDays=1 is the last 24 hours, in UTC),
not a calendar day, and allows only 10 calls per project per day, so it's used by the daily report only.
The live API's field names and number types differ from Microsoft's documented sample (counts have come
back both as strings and as numbers), so every value is read defensively.
"""
from __future__ import annotations

import datetime as dt

from .http import SourceError, request_json

URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=1"

# metricName -> the share of visits in which it happened, from sessionsWithMetricPercentage (0-100)
ISSUE_METRICS = {"RageClickCount": "rage_clicks", "DeadClickCount": "dead_clicks", "ScriptErrorCount": "script_errors",
                 "ErrorClickCount": "error_clicks", "QuickbackClick": "quick_backs"}


def last_24_hours(token: str) -> dict:
    """Visits, pages per visit, time per visit and how often visitors hit problems, for the last 24 hours."""
    fetched_at = dt.datetime.now(dt.timezone.utc)
    groups = request_json("Clarity", URL, token=token, attempts=2)  # each call uses 1 of 10 a day
    if not isinstance(groups, list):
        raise SourceError("Clarity's response isn't a list of metrics.")
    by_name = {g.get("metricName"): (g.get("information") or [{}])[0] for g in groups if isinstance(g, dict)}
    traffic = by_name.get("Traffic")
    if traffic is None:
        raise SourceError("Clarity's response has no Traffic figures.")
    engagement = by_name.get("EngagementTime", {})
    return {
        "fetched_at": fetched_at.strftime("%Y-%m-%d %H:%M"),
        "visits": _int(traffic.get("totalSessionCount")),  # bot visits are counted separately and left out
        "bot_visits": _int(traffic.get("totalBotSessionCount")),
        "pages_per_visit": _num(traffic.get("pagesPerSessionPercentage", traffic.get("PagesPerSessionPercentage"))),
        "active_secs": _num(engagement.get("activeTime")),  # average per visit
        "scroll_depth": _num(by_name.get("ScrollDepth", {}).get("averageScrollDepth")),
        "issues": {key: _num(by_name.get(name, {}).get("sessionsWithMetricPercentage"))
                   for name, key in ISSUE_METRICS.items()},
    }


def _num(value) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int:
    x = _num(value)
    return int(x) if x is not None else 0
