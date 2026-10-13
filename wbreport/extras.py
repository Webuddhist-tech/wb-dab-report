"""Optional figures from Airbridge, Firebase and Clarity, shown next to the PostHog numbers.

Each source runs only when its settings are present. A failure in one never stops the report: that
section is left out, the message says so in one line, and the Actions log gets a warning without
any numbers in it.
"""
from __future__ import annotations

import datetime as dt
import os
import traceback
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import airbridge, clarity, config, firebase
from .http import SourceError
from .periods import DAY, Period

# Firebase exports crash and session data once a day at no fixed time, so the day before yesterday
# is the latest day that's reliably complete when the reports run.
CRASH_DAYS_BEHIND = 2


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _app_today(tz_name: str) -> dt.date:
    try:
        return dt.datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise SourceError(f"'{tz_name}' isn't a timezone name. Use one like Asia/Kolkata.") from None


def _google() -> tuple[str, str]:
    token, project = env("GOOGLE_ACCESS_TOKEN"), env("FIREBASE_PROJECT_ID")
    if not project:
        raise SourceError("Set the FIREBASE_PROJECT_ID variable.")
    if not token:
        raise SourceError("The Google Cloud sign-in step didn't run. Set the GCP_WORKLOAD_IDENTITY_PROVIDER "
                          "and GCP_SERVICE_ACCOUNT variables.")
    return token, project


# ---------- Airbridge ----------

def _airbridge(report: str, cur: Period, prev: Period, today: dt.date, picked: bool) -> dict | None:
    token, app, tz_name = env("AIRBRIDGE_API_TOKEN"), env("AIRBRIDGE_APP"), env("AIRBRIDGE_TIMEZONE")
    if not token:
        return None
    if not app or not tz_name:
        raise SourceError("Set the AIRBRIDGE_APP and AIRBRIDGE_TIMEZONE variables to match Airbridge's "
                          "Settings > App Settings.")
    if report == "daily" and not picked:
        # Airbridge's days run in the app's timezone, so "yesterday" is yesterday there.
        day = _app_today(tz_name) - DAY
        cur, prev = Period(day, day + DAY), Period(day - DAY, day)
    return {
        "timezone": tz_name,
        "start": cur.start.isoformat(),
        "end": cur.last.isoformat(),
        "channels": airbridge.installs_by_channel(token, app, cur.start, cur.last),
        "prev_total": sum(r["installs"] for r in airbridge.installs_by_channel(token, app, prev.start, prev.last)),
    }


# ---------- Firebase ----------

def _crashes(report: str, cur: Period, prev: Period, today: dt.date, picked: bool) -> dict | None:
    location = env("BIGQUERY_LOCATION")
    if not location:
        return None
    token, project = _google()
    platforms = [p.strip().upper() for p in (env("CRASHLYTICS_PLATFORMS") or "ANDROID,IOS").split(",") if p.strip()]
    latest, partial = today - DAY * CRASH_DAYS_BEHIND, False
    if report == "daily" and (not picked or cur.start > latest):
        if picked:
            raise SourceError(f"Firebase may not have all crash data for {cur.start} yet (latest full day {latest}).")
        cur, prev = Period(latest, latest + DAY), Period(latest - DAY, latest)
    elif cur.end > latest + DAY:  # the week or month runs past the latest complete day: stop there
        if cur.start > latest:
            raise SourceError(f"Firebase has no complete crash data for this period yet (latest day {latest}).")
        cur, partial = Period(cur.start, latest + DAY), True
    data = firebase.crash_free(token, project, location, env("CRASHLYTICS_APP_ID") or config.APP_NAMESPACE,
                               platforms, cur, prev)
    data["partial"] = partial
    return data


def _notifications(report: str, cur: Period, prev: Period, today: dt.date, picked: bool) -> dict | None:
    app_id = env("FIREBASE_ANDROID_APP_ID")
    if not app_id:
        return None
    token, project = _google()
    days = firebase.delivery_by_day(token, project, app_id)
    if report != "daily":
        return {"days": days, "prev": None}  # Firebase keeps about a week, so there's no week before to compare
    i = len(days) - 1
    if picked:
        dates = [x["date"] for x in days]
        if cur.start.isoformat() not in dates:
            raise SourceError(f"Firebase only has delivery data from {dates[0]} to {dates[-1]}.")
        i = dates.index(cur.start.isoformat())
    return {"days": [days[i]], "prev": days[i - 1] if i > 0 else None}


# ---------- Clarity ----------

def _clarity(report: str, cur: Period, prev: Period, today: dt.date, picked: bool) -> dict | None:
    token = env("CLARITY_API_TOKEN")
    # The API covers only the 24 hours before the call: nothing for a picked date, a week or a month.
    if not token or report != "daily" or picked:
        return None
    return clarity.last_24_hours(token)


# ---------- collecting ----------

SOURCES = [
    # (key in the result, name in messages, function)
    ("installs", "Airbridge", _airbridge),
    ("crashes", "Crashlytics", _crashes),
    ("notifications", "Firebase notification", _notifications),
    ("website", "Clarity", _clarity),
]


def collect(report: str, cur: Period, prev: Period, today: dt.date, picked: bool = False) -> dict:
    """{key: data or None for each source, "notes": [one line per source that failed]}.

    picked: the date came from --date, so each source reports on it instead of its own latest day.
    """
    out: dict = {"notes": []}
    for key, name, fetch in SOURCES:
        out[key] = None
        try:
            out[key] = fetch(report, cur, prev, today, picked)
        except SourceError as err:
            print(f"::warning::Left out the {name} figures: {err}")
            out["notes"].append(f"{name} figures couldn't be fetched this time.")
        except Exception as err:  # unexpected: say where, not the message, which could hold data
            frame = traceback.extract_tb(err.__traceback__)[-1]
            print(f"::warning::Left out the {name} figures: unexpected {type(err).__name__} in "
                  f"{os.path.basename(frame.filename)}, line {frame.lineno}.")
            out["notes"].append(f"{name} figures couldn't be fetched this time.")
    return out
