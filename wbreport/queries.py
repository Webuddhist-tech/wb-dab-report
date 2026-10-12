"""HogQL queries and the aggregate numbers each report needs.

Every query returns counts of people, event counts or medians. No person IDs or per-person rows
leave PostHog. Days are UTC days (the project's timezone).
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from . import config
from .periods import DAY, Period

Run = Callable[[str], list[dict]]

SIGNED_IN = ("auth_login_succeeded", "auth_guest_started")
SETUP_DONE = "onboarding_completed"
FIRST_PRACTICE = ("reader_opened", "group_event_live_entered", "plan_day_viewed", "mala_session_started",
                  "timer_started", "recitation_collection_opened")

# report key -> column in q_period_activity
ACTIVITY_COLUMNS = {
    "read": "readers", "live": "live_people", "plan_open": "plan_openers", "plan_day": "plan_day_people",
    "plan_days_completed": "plan_days_completed", "mala": "mala_people", "mala_rounds": "mala_rounds",
    "timer": "timer_people",
}


def _ts(day: dt.date) -> str:
    return f"'{day.isoformat()}'"


def _in(names: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{x}'" for x in names) + ")"


def _period(cur_start: dt.date, column: str = "timestamp") -> str:
    return f"if({column} >= {_ts(cur_start)}, 'cur', 'prev')"


# ---------- per-day series ----------

def q_daily_activity(start: dt.date, end: dt.date) -> str:
    """People per day: opened the app (by platform), read a text, opened a notification, joined a live session."""
    return f"""
SELECT toString(toDate(timestamp)) AS day,
       toInt(count(DISTINCT if(event = '$screen', person_id, NULL))) AS people,
       toInt(count(DISTINCT if(event = '$screen' AND properties.$os = 'Android', person_id, NULL))) AS android,
       toInt(count(DISTINCT if(event = '$screen' AND properties.$os != 'Android', person_id, NULL))) AS apple,
       toInt(count(DISTINCT if(event = 'reader_opened', person_id, NULL))) AS readers,
       toInt(count(DISTINCT if(event = '$push_notification_opened', person_id, NULL))) AS push_open_people,
       toInt(count(DISTINCT if(event = 'group_event_live_entered', person_id, NULL))) AS live_people
FROM events
WHERE timestamp >= {_ts(start)}
  AND timestamp < {_ts(end)}
  AND event IN ('$screen', 'reader_opened', '$push_notification_opened', 'group_event_live_entered')
GROUP BY day
ORDER BY day
LIMIT 500
"""


def q_daily_new(start: dt.date, end: dt.date) -> str:
    """People whose first-ever screen view falls on each day."""
    return f"""
SELECT toString(toDate(first_seen)) AS day,
       toInt(count()) AS new_people
FROM (
  SELECT person_id, min(timestamp) AS first_seen
  FROM events
  WHERE event = '$screen'
    AND timestamp >= {_ts(config.HISTORY_START)}
    AND timestamp < {_ts(end)}
  GROUP BY person_id
)
WHERE first_seen >= {_ts(start)}
GROUP BY day
ORDER BY day
LIMIT 500
"""


def _person_days(start: dt.date, end: dt.date) -> str:
    """Seconds in the app per person per day: each app session runs from its first to its last event."""
    return f"""
  SELECT day, person_id, sum(secs) AS user_secs
  FROM (
    SELECT properties.$session_id AS sid,
           toDate(min(timestamp)) AS day,
           any(person_id) AS person_id,
           dateDiff('second', min(timestamp), max(timestamp)) AS secs
    FROM events
    WHERE timestamp >= {_ts(start)}
      AND timestamp < {_ts(end)}
      AND properties.$session_id IN (
        SELECT properties.$session_id
        FROM events
        WHERE event = '$screen'
          AND properties.$session_id IS NOT NULL
          AND timestamp >= {_ts(start)}
          AND timestamp < {_ts(end)}
      )
    GROUP BY sid
  )
  GROUP BY day, person_id"""


def q_daily_time(start: dt.date, end: dt.date) -> str:
    """Median ("typical") and average time in the app per person, per day."""
    return f"""
SELECT toString(day) AS day,
       toInt(round(quantile(0.5)(user_secs))) AS median_secs,
       toInt(round(avg(user_secs))) AS avg_secs
FROM ({_person_days(start, end)}
)
GROUP BY day
ORDER BY day
LIMIT 500
"""


# ---------- this period vs the previous one ----------

def q_period_activity(prev: Period, cur: Period) -> str:
    return f"""
SELECT {_period(cur.start)} AS period,
       toInt(count(DISTINCT if(event = '$screen', person_id, NULL))) AS people,
       toInt(count(DISTINCT if(event = 'reader_opened', person_id, NULL))) AS readers,
       toInt(count(DISTINCT if(event = 'group_event_live_entered', person_id, NULL))) AS live_people,
       toInt(count(DISTINCT if(event = 'plan_viewed', person_id, NULL))) AS plan_openers,
       toInt(count(DISTINCT if(event = 'plan_day_completed', person_id, NULL))) AS plan_day_people,
       toInt(countIf(event = 'plan_day_completed')) AS plan_days_completed,
       toInt(count(DISTINCT if(event = 'mala_session_started', person_id, NULL))) AS mala_people,
       toInt(countIf(event = 'mala_round_completed')) AS mala_rounds,
       toInt(count(DISTINCT if(event = 'timer_completed', person_id, NULL))) AS timer_people
FROM events
WHERE timestamp >= {_ts(prev.start)}
  AND timestamp < {_ts(cur.end)}
  AND event IN ('$screen', 'reader_opened', 'group_event_live_entered', 'plan_viewed', 'plan_day_completed',
                'mala_session_started', 'mala_round_completed', 'timer_completed')
GROUP BY period
"""


def q_period_time(prev: Period, cur: Period) -> str:
    return f"""
SELECT if(day >= toDate({_ts(cur.start)}), 'cur', 'prev') AS period,
       toInt(round(quantile(0.5)(user_secs))) AS median_secs
FROM ({_person_days(prev.start, cur.end)}
)
GROUP BY period
"""


def q_splits(prev: Period, cur: Period) -> str:
    """Each person counted once: the platform they used most, and the language they read in most."""
    return f"""
SELECT period, kind, key, toInt(count()) AS people
FROM (
  SELECT period, 'platform' AS kind, argMax(platform, n) AS key
  FROM (
    SELECT {_period(cur.start)} AS period,
           person_id,
           if(properties.$os = 'Android', 'Android', 'iPhone & iPad') AS platform,
           count() AS n
    FROM events
    WHERE event = '$screen'
      AND timestamp >= {_ts(prev.start)}
      AND timestamp < {_ts(cur.end)}
    GROUP BY period, person_id, platform
  )
  GROUP BY period, person_id
  UNION ALL
  SELECT period, 'language' AS kind, argMax(language, n) AS key
  FROM (
    SELECT {_period(cur.start)} AS period,
           person_id,
           coalesce(properties.language, 'unknown') AS language,
           count() AS n
    FROM events
    WHERE event = 'reader_opened'
      AND timestamp >= {_ts(prev.start)}
      AND timestamp < {_ts(cur.end)}
    GROUP BY period, person_id, language
  )
  GROUP BY period, person_id
)
GROUP BY period, kind, key
ORDER BY period, kind, people DESC
LIMIT 500
"""


def q_came_back(prev: Period, cur: Period) -> str:
    """Of the people who were new in the previous period, how many opened the app in this one."""
    return f"""
SELECT toInt(count()) AS cohort,
       toInt(countIf(active_now > 0)) AS back
FROM (
  SELECT person_id,
         min(timestamp) AS first_seen,
         countIf(timestamp >= {_ts(cur.start)}) AS active_now
  FROM events
  WHERE event = '$screen'
    AND timestamp >= {_ts(config.HISTORY_START)}
    AND timestamp < {_ts(cur.end)}
  GROUP BY person_id
  HAVING first_seen >= {_ts(prev.start)} AND first_seen < {_ts(cur.start)}
)
"""


def q_funnel(prev: Period, cur: Period) -> str:
    """People who installed in each period, and how far they got, in order, within 24 hours of installing."""
    events = ("Application Installed",) + SIGNED_IN + (SETUP_DONE,) + FIRST_PRACTICE
    return f"""
SELECT {_period(cur.start, 'installed_at')} AS period,
       toInt(count()) AS installed,
       toInt(countIf(steps >= 2)) AS signed_in,
       toInt(countIf(steps >= 3)) AS finished_setup,
       toInt(countIf(steps >= 4)) AS tried_practice
FROM (
  SELECT person_id,
         minIf(timestamp, event = 'Application Installed') AS installed_at,
         windowFunnel(86400)(toUnixTimestamp(timestamp),
                             event = 'Application Installed',
                             event IN {_in(SIGNED_IN)},
                             event = '{SETUP_DONE}',
                             event IN {_in(FIRST_PRACTICE)}) AS steps
  FROM events
  WHERE timestamp >= {_ts(prev.start)}
    AND timestamp < {_ts(cur.end + DAY)}
    AND event IN {_in(events)}
  GROUP BY person_id
  HAVING installed_at >= {_ts(prev.start)} AND installed_at < {_ts(cur.end)}
)
GROUP BY period
"""


def q_top_content(cur: Period, texts: int = 5, plans: int = 3) -> str:
    """Most-read texts (people) and most-opened plans (people who opened, people who finished a day)."""
    return f"""
SELECT kind, title, lang, people, extra
FROM (
  SELECT 'text' AS kind,
         coalesce(properties.text_title, '') AS title,
         coalesce(properties.language, '') AS lang,
         toInt(count(DISTINCT person_id)) AS people,
         toInt(0) AS extra
  FROM events
  WHERE event = 'reader_opened'
    AND timestamp >= {_ts(cur.start)}
    AND timestamp < {_ts(cur.end)}
  GROUP BY title, lang
  HAVING title != ''
  ORDER BY people DESC
  LIMIT {texts}
)
UNION ALL
SELECT kind, title, lang, people, extra
FROM (
  SELECT 'plan' AS kind,
         coalesce(properties.plan_name, '') AS title,
         '' AS lang,
         toInt(count(DISTINCT if(event = 'plan_viewed', person_id, NULL))) AS people,
         toInt(count(DISTINCT if(event = 'plan_day_completed', person_id, NULL))) AS extra
  FROM events
  WHERE event IN ('plan_viewed', 'plan_day_completed')
    AND timestamp >= {_ts(cur.start)}
    AND timestamp < {_ts(cur.end)}
  GROUP BY title
  HAVING title != ''
  ORDER BY people DESC
  LIMIT {plans}
)
"""


# ---------- assembling the numbers ----------

def _num(value) -> int:
    return int(value or 0)


def _by_day(rows: list[dict], key: str, dates: list[dt.date]) -> list[int]:
    found = {str(r["day"]): r[key] for r in rows}
    return [_num(found.get(day.isoformat())) for day in dates]


def daily_series(run: Run, day: dt.date, days: int = 15) -> dict:
    """The report day and the 14 days before it (7 for the average, the rest for "in a row" streaks)."""
    start, end = day - DAY * (days - 1), day + DAY
    dates = [start + DAY * i for i in range(days)]
    activity = run(q_daily_activity(start, end))
    if not any(_num(r["people"]) for r in activity):
        raise ValueError(f"PostHog has no app activity between {start} and {day}.")
    new = run(q_daily_new(start, end))
    times = run(q_daily_time(start, end))
    series = {"dates": [x.isoformat() for x in dates]}
    for key in ("people", "android", "apple", "readers", "push_open_people", "live_people"):
        series[key] = _by_day(activity, key, dates)
    series["new"] = _by_day(new, "new_people", dates)
    series["typical_secs"] = _by_day(times, "median_secs", dates)
    series["avg_secs"] = _by_day(times, "avg_secs", dates)
    return series


def period_data(run: Run, prev: Period, cur: Period) -> dict:
    """Everything the weekly and monthly reports show, for this period ('cur') and the one before ('prev')."""
    dates = prev.dates() + cur.dates()
    people_by_day = _by_day(run(q_daily_activity(prev.start, cur.end)), "people", dates)
    new_by_day = _by_day(run(q_daily_new(prev.start, cur.end)), "new_people", dates)
    activity = {r["period"]: r for r in run(q_period_activity(prev, cur))}
    times = {r["period"]: r["median_secs"] for r in run(q_period_time(prev, cur))}
    splits = run(q_splits(prev, cur))
    came_back = run(q_came_back(prev, cur))
    funnel = {r["period"]: r for r in run(q_funnel(prev, cur))}
    top = run(q_top_content(cur))

    def block(name: str, period: Period, offset: int) -> dict:
        act, fun = activity.get(name, {}), funnel.get(name, {})
        window = slice(offset, offset + period.days)
        platform = {"Android": 0, "iPhone & iPad": 0}
        languages: dict[str, int] = {}
        for r in splits:
            if r["period"] == name and r["kind"] == "platform":
                platform[r["key"]] = _num(r["people"])
            elif r["period"] == name and r["kind"] == "language":
                languages[r["key"]] = _num(r["people"])
        return {
            "start": period.start.isoformat(),
            "end": period.last.isoformat(),
            "people": _num(act.get("people")),
            "new": sum(new_by_day[window]),
            "daily_dates": [x.isoformat() for x in period.dates()],
            "daily_people": people_by_day[window],
            "daily_new": new_by_day[window],
            "typical_secs": _num(times.get(name)),
            "activities": {key: _num(act.get(col)) for key, col in ACTIVITY_COLUMNS.items()},
            "platform": platform,
            "languages": languages,
            "funnel": [_num(fun.get(k)) for k in ("installed", "signed_in", "finished_setup", "tried_practice")],
            "came_back": None,
        }

    before, now = block("prev", prev, 0), block("cur", cur, prev.days)
    if came_back and _num(came_back[0]["cohort"]):
        now["came_back"] = {"cohort": _num(came_back[0]["cohort"]), "back": _num(came_back[0]["back"])}
    texts = sorted((r for r in top if r["kind"] == "text"), key=lambda r: -_num(r["people"]))
    plans = sorted((r for r in top if r["kind"] == "plan"), key=lambda r: -_num(r["people"]))
    now["top_texts"] = [[r["title"], r["lang"], _num(r["people"])] for r in texts]
    now["top_plans"] = [[r["title"], _num(r["people"]), _num(r["extra"])] for r in plans]
    return {"cur": now, "prev": before}
