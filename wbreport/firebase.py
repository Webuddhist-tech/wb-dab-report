"""Crash-free users (Crashlytics, through its BigQuery export) and push delivery (FCM Data API).

Standard library only. The Google access token comes from the workflow's keyless sign-in
(google-github-actions/auth with Workload Identity Federation), so no Google key is stored anywhere.

- Crash-free users = 1 - people with a crash / people who opened the app, counted per installation as
  Firebase does, from the firebase_crashlytics and firebase_sessions datasets. Firebase exports these once
  a day at no fixed time, so the latest day may not be there yet.
- Delivery data covers Android only, comes from phones that share usage data with Google, and runs up to
  5 days behind, so it's reported for the newest days Firebase has, with their dates.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import urllib.parse

from .http import SourceError, request_json
from .periods import Period

BIGQUERY = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
FCM_DATA = "https://fcmdata.googleapis.com/v1beta1/projects/{project}/androidApps/{app}/deliveryData?pageSize=1000"
MAX_BYTES = 2_000_000_000  # refuse any query that would bill more than 2 GB
QUERY_SECONDS = 180

PLATFORM_NAMES = {"ANDROID": "Android", "IOS": "iPhone & iPad"}
DROPPED = ("droppedTooManyPendingMessages", "droppedAppForceStopped", "droppedDeviceInactive", "droppedTtlExpired")


# ---------- crash-free users ----------

def crash_free(token: str, project: str, location: str, namespace: str, platforms: list[str],
               cur: Period, prev: Period) -> dict:
    """People who opened the app and people who had a crash, in `cur` and `prev`, per platform."""
    if not re.fullmatch(r"[A-Za-z0-9.:-]+", project):
        raise SourceError("FIREBASE_PROJECT_ID doesn't look like a Google Cloud project ID.")
    table = namespace.replace(".", "_")
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise SourceError("The app ID for the Crashlytics tables can only hold letters, digits, dots and underscores.")
    if not platforms or any(p not in PLATFORM_NAMES for p in platforms):
        raise SourceError("CRASHLYTICS_PLATFORMS must list ANDROID, IOS or both, separated by a comma.")

    def union(dataset: str, id_column: str, where: str = "") -> str:
        return " UNION ALL ".join(
            f"SELECT '{p}' AS platform, event_timestamp AS ts, {id_column} AS id "
            f"FROM `{project}.{dataset}.{table}_{p}`{where}" for p in platforms)

    window = f"ts >= TIMESTAMP('{prev.start}') AND ts < TIMESTAMP('{cur.end}')"
    period = f"IF(ts >= TIMESTAMP('{cur.start}'), 'cur', 'prev')"
    sql = f"""
SELECT 'active' AS kind, platform, {period} AS period, COUNT(DISTINCT id) AS people
FROM ({union('firebase_sessions', 'instance_id')})
WHERE {window}
GROUP BY kind, platform, period
UNION ALL
SELECT 'crashed' AS kind, platform, {period} AS period, COUNT(DISTINCT id) AS people
FROM ({union('firebase_crashlytics', 'installation_uuid', " WHERE error_type = 'FATAL'")})
WHERE {window}
GROUP BY kind, platform, period
"""
    counts = {(r["kind"], r["platform"], r["period"]): int(r["people"] or 0)
              for r in bigquery_rows(token, project, location, sql)}

    def block(name: str) -> dict:
        by_platform = {PLATFORM_NAMES[p]: (counts.get(("active", p, name), 0), counts.get(("crashed", p, name), 0))
                       for p in platforms}
        return {"active": sum(a for a, _ in by_platform.values()),
                "crashed": sum(c for _, c in by_platform.values()), "by_platform": by_platform}

    now, before = block("cur"), block("prev")
    if not now["active"]:
        raise SourceError(f"Firebase has no session data from {cur.start} to {cur.last} yet. Check that "
                          "'Include sessions' is on in Firebase's BigQuery export settings.")
    if now["crashed"] > now["active"]:
        raise SourceError("More people crashed than opened the app, so the crash and session exports don't line up.")
    return {"start": cur.start.isoformat(), "end": cur.last.isoformat(), "cur": now, "prev": before}


def bigquery_rows(token: str, project: str, location: str, sql: str) -> list[dict]:
    """Run one standard-SQL query and return its rows as dicts. Every value arrives as a string or None."""
    url = BIGQUERY.format(project=urllib.parse.quote(project, safe=""))
    body = {"query": sql, "useLegacySql": False, "timeoutMs": 60000, "location": location,
            "maximumBytesBilled": str(MAX_BYTES), "labels": {"source": "wbreport"}}
    result = request_json("BigQuery", url, method="POST", token=token, body=body, timeout=90)
    deadline = time.monotonic() + QUERY_SECONDS
    while not result.get("jobComplete"):
        if time.monotonic() > deadline:
            raise SourceError(f"The BigQuery query was still running after {QUERY_SECONDS} seconds.")
        job = result.get("jobReference", {})
        poll = (f"{url}/{urllib.parse.quote(job.get('jobId', ''), safe='')}"
                f"?location={urllib.parse.quote(job.get('location') or location)}&timeoutMs=60000")
        result = request_json("BigQuery", poll, token=token, timeout=90)
    names = [f["name"] for f in result.get("schema", {}).get("fields", [])]
    return [{name: cell.get("v") for name, cell in zip(names, row.get("f", []))} for row in result.get("rows", [])]


# ---------- push delivery ----------

def delivery_by_day(token: str, project: str, app_id: str) -> list[dict]:
    """Delivery outcomes per day for the days Firebase has (about a week, ending up to 5 days ago), oldest first.

    Each item: {"date": "YYYY-MM-DD", "accepted": messages Firebase accepted for Android phones,
    "delivered" / "pending" / "dropped" / "collapsed": percent of those, weighted across message labels}.
    """
    url = FCM_DATA.format(project=urllib.parse.quote(project, safe=""), app=urllib.parse.quote(app_id, safe=":"))
    entries, page_token = [], ""
    for _ in range(10):
        page = request_json("Firebase Cloud Messaging", url + (f"&pageToken={urllib.parse.quote(page_token)}"
                                                               if page_token else ""), token=token)
        entries += page.get("androidDeliveryData", [])
        page_token = page.get("nextPageToken", "")
        if not page_token:
            break

    days: dict[str, dict] = {}
    for e in entries:
        date = e.get("date", {})
        try:
            key = dt.date(int(date["year"]), int(date["month"]), int(date["day"])).isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        data = e.get("data", {})
        n = int(data.get("countMessagesAccepted") or 0)  # int64 values arrive as strings
        outcome = data.get("messageOutcomePercents", {})
        day = days.setdefault(key, {"date": key, "accepted": 0, "delivered": 0.0, "pending": 0.0,
                                    "dropped": 0.0, "collapsed": 0.0})
        day["accepted"] += n
        day["delivered"] += n * float(outcome.get("delivered") or 0)
        day["pending"] += n * float(outcome.get("pending") or 0)
        day["collapsed"] += n * float(outcome.get("collapsed") or 0)
        day["dropped"] += n * sum(float(outcome.get(k) or 0) for k in DROPPED)

    out = []
    for key in sorted(days):
        day = days[key]
        if day["accepted"]:
            for k in ("delivered", "pending", "dropped", "collapsed"):
                day[k] /= day["accepted"]
            out.append(day)
    if not out:
        raise SourceError("Firebase has no delivery data for the last week. It only covers Android phones that "
                          "share usage data with Google, and skips days with too few messages.")
    return out
