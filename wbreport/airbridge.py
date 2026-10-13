"""Installs by channel from Airbridge's Actuals Report API (v7). Standard library only.

Airbridge counts days in the app's own timezone (Settings > App Settings), not UTC, and corrects the
previous two days at 9 PM UTC, so the latest day can still rise slightly. Organic installs (no ad or
tracking link) come back under the channel "unattributed".
"""
from __future__ import annotations

import datetime as dt
import time
import urllib.parse

from .http import SourceError, request_json

QUERY_URL = "https://api.airbridge.io/reports/api/v7/apps/{app}/actuals/query"
PAGE_SIZE = 100
MAX_PAGES = 10      # 1,000 channels is far more than any real app has
POLL_SECONDS = 120  # give up on a report that's still running after this long


def installs_by_channel(token: str, app: str, start: dt.date, last: dt.date) -> list[dict]:
    """Installs per channel from `start` to `last` (inclusive, app timezone), largest first.

    Each item: {"channel": Airbridge's channel key, "installs": int, "masked": bool}. Masked counts are
    rounded down by Airbridge under Meta's privacy rules and shown in its dashboard as "+α".
    """
    url = QUERY_URL.format(app=urllib.parse.quote(app, safe=""))
    body = {
        "from": start.isoformat(),
        "to": last.isoformat(),
        "groupBys": ["channel"],
        "metrics": ["app_installs"],
        "filters": [],
        "sorts": [{"fieldName": "app_installs", "isAscending": False}],
    }
    task = request_json("Airbridge", url, method="POST", token=token, body=body).get("task", {})
    task_id = task.get("taskId")
    if not task_id:
        raise SourceError("Airbridge didn't return a report task.")

    page = _wait_for(token, f"{url}/{urllib.parse.quote(task_id, safe='')}")
    rows = _rows(page)
    skip = PAGE_SIZE
    while page.get("pagination", {}).get("hasNext") and skip < PAGE_SIZE * MAX_PAGES:
        page = request_json("Airbridge", _page_url(url, task_id, skip), token=token)
        rows += _rows(page)
        skip += PAGE_SIZE
    return rows


def _page_url(url: str, task_id: str, skip: int) -> str:
    return f"{url}/{urllib.parse.quote(task_id, safe='')}?skip={skip}&size={PAGE_SIZE}"


def _wait_for(token: str, task_url: str) -> dict:
    """Poll the report task until it finishes. Returns the first page of results."""
    deadline, wait = time.monotonic() + POLL_SECONDS, 2.0
    while True:
        page = request_json("Airbridge", f"{task_url}?skip=0&size={PAGE_SIZE}", token=token)
        status = page.get("task", {}).get("status")
        if status == "SUCCESS":
            return page
        if status in ("FAILURE", "CANCELED"):
            raise SourceError(f"Airbridge couldn't build the report (status {status}).")
        if time.monotonic() > deadline:
            raise SourceError(f"Airbridge's report was still {status or 'not ready'} after {POLL_SECONDS} seconds.")
        time.sleep(wait)
        wait = min(wait * 1.5, 10)


def _rows(page: dict) -> list[dict]:
    out = []
    for row in page.get("actuals", {}).get("data", {}).get("rows", []):
        groups = row.get("groupBys") or [""]
        metric = row.get("values", {}).get("app_installs", {})
        out.append({"channel": str(groups[0] or ""), "installs": int(metric.get("value") or 0),
                    "masked": bool(metric.get("isMasked"))})
    return out
