"""Build one analytics report from PostHog and post it to Discord.

    python -m wbreport daily|weekly|monthly [--date YYYY-MM-DD] [--target production|test] [--dry-run DIR]

The repository is public, so this script never prints the numbers themselves: logs only say which
report was built and where it went.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback

from . import config, discord, periods, queries, text
from .posthog import Client, PostHogError

WEBHOOK_ENV = {"production": "DISCORD_WEBHOOK_URL", "test": "DISCORD_TEST_WEBHOOK_URL"}


def build(report: str, run, date=None, today=None, chart_dir: str | None = None):
    """Return (payload, chart files [(filename, bytes)], label for the logs)."""
    today = today or periods.utc_today()
    if report == "daily":
        day = periods.daily_day(today, date)
        payload = text.daily_payload(queries.daily_series(run, day))
        return payload, [], f"daily report for {day}"

    cur, prev, preview = (periods.week_periods if report == "weekly" else periods.month_periods)(today, date)
    data = queries.period_data(run, prev, cur)
    data["cur"]["preview"] = preview
    label = f"{report} report for {cur.start} to {cur.last}" + (" (so far)" if preview else "")

    chart_dir = chart_dir or tempfile.mkdtemp(prefix="wbreport-")
    os.makedirs(chart_dir, exist_ok=True)
    try:
        from . import charts  # matplotlib is only needed for the weekly and monthly reports
        specs = charts.period_charts(report, data["cur"], data["prev"], chart_dir)
    except Exception as err:  # a broken chart shouldn't stop the report: post the text instead
        print(f"::warning::Couldn't draw the charts ({type(err).__name__}). Posting text only.")
        payload = text.period_payload(report, data["cur"], data["prev"])
        return discord.without_charts(payload), [], label
    files = []
    for filename, _alt in specs:
        with open(os.path.join(chart_dir, filename), "rb") as fh:
            files.append((filename, fh.read()))
    return text.period_payload(report, data["cur"], data["prev"], charts=specs), files, label


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wbreport", description=__doc__.splitlines()[0])
    parser.add_argument("report", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--date", help="Daily: the day to report on. Weekly/monthly: any day in the week or month. "
                                       "YYYY-MM-DD in UTC. Defaults to the last complete day, week or month.")
    parser.add_argument("--target", choices=["production", "test"], default="test",
                        help="Which Discord channel to post to (default: test).")
    parser.add_argument("--dry-run", metavar="DIR", help="Write the message and charts to DIR instead of posting.")
    args = parser.parse_args(argv)

    try:
        date = periods.parse_date(args.date)
        if args.dry_run:
            os.makedirs(args.dry_run, exist_ok=True)
        client = Client(os.environ.get("POSTHOG_API_KEY", "").strip())
        payload, files, label = build(args.report, client.run, date, chart_dir=args.dry_run)
        text.check_limits(payload)

        if args.dry_run:
            with open(os.path.join(args.dry_run, f"{args.report}.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            print(f"Built the {label}. Wrote the message and {len(files)} chart(s) to {args.dry_run}.")
            return 0

        webhook = os.environ.get(WEBHOOK_ENV[args.target], "").strip()
        if not webhook:
            raise RuntimeError(f"{WEBHOOK_ENV[args.target]} isn't set, so there's nowhere to post the {args.target} "
                               "report. Add it under Settings > Secrets and variables > Actions.")
        with_charts = discord.send_report(webhook, payload, files)
        charts_note = f" with {len(files)} chart(s)" if with_charts else ""
        print(f"Posted the {label} to the {args.target} channel{charts_note}.")
        return 0
    except (periods.PeriodError, PostHogError, discord.DiscordError, RuntimeError, ValueError) as err:
        print(f"::error::{err}")  # GitHub shows ::error:: lines as annotations on the run
        return 1
    except Exception as err:  # unexpected: say where, not the message, which could hold report data or a key
        frame = traceback.extract_tb(err.__traceback__)[-1]
        print(f"::error::Unexpected {type(err).__name__} in {os.path.basename(frame.filename)}, line {frame.lineno}.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
