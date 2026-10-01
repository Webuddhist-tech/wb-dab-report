"""
Daily Active Users -> Discord.

Pulls yesterday's 1-day / 7-day / 28-day active users from the Google Analytics
(GA4) property linked to Firebase, and posts them to a Discord webhook.

Required environment variables (set as GitHub Actions secrets):
  GA4_PROPERTY_ID           numeric GA4 property ID, e.g. 412345678
  GA4_SERVICE_ACCOUNT_JSON  full JSON key of a service account with Viewer access
  DISCORD_WEBHOOK_URL       the Discord webhook URL

Optional:
  PLATFORM                  "iOS", "Android" or "web" to report one platform only
                            (leave empty for all platforms combined)
  APP_NAME                  title shown in the Discord message
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    OrderBy,
    RunReportRequest,
)
from google.oauth2 import service_account

PROPERTY_ID = os.environ["GA4_PROPERTY_ID"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
SERVICE_ACCOUNT_INFO = json.loads(os.environ["GA4_SERVICE_ACCOUNT_JSON"])
PLATFORM = os.environ.get("PLATFORM", "").strip()
APP_NAME = os.environ.get("APP_NAME", "WeBuddhist").strip()


def fetch_active_users():
    """Return {date(YYYYMMDD): {"d1": int, "d7": int, "d28": int}} for the last 8 days."""
    creds = service_account.Credentials.from_service_account_info(
        SERVICE_ACCOUNT_INFO,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="active1DayUsers"),
            Metric(name="active7DayUsers"),
            Metric(name="active28DayUsers"),
        ],
        # "yesterday" is the last complete day in the property's reporting time zone.
        date_ranges=[DateRange(start_date="8daysAgo", end_date="yesterday")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
    )
    if PLATFORM:
        request.dimension_filter = FilterExpression(
            filter=Filter(
                field_name="platform",
                string_filter=Filter.StringFilter(value=PLATFORM),
            )
        )

    response = client.run_report(request)
    data = {}
    for row in response.rows:
        date = row.dimension_values[0].value
        d1, d7, d28 = (int(v.value) for v in row.metric_values)
        data[date] = {"d1": d1, "d7": d7, "d28": d28}
    return data


def pct_change(new, old):
    if not old:
        return "n/a"
    change = (new - old) / old * 100
    arrow = "▲" if change > 0 else "▼" if change < 0 else "■"
    return f"{arrow} {change:+.1f}%"


def build_message(data):
    yesterday = dt.date.today() - dt.timedelta(days=1)
    key = lambda d: d.strftime("%Y%m%d")
    empty = {"d1": 0, "d7": 0, "d28": 0}

    today_row = data.get(key(yesterday), empty)
    prev_day = data.get(key(yesterday - dt.timedelta(days=1)), empty)
    last_week = data.get(key(yesterday - dt.timedelta(days=7)), empty)

    scope = f" ({PLATFORM})" if PLATFORM else ""
    return {
        "username": "DAU Bot",
        "embeds": [
            {
                "title": f"📊 {APP_NAME} — Daily Active Users{scope}",
                "description": f"**{yesterday.strftime('%A, %d %b %Y')}**",
                "color": 0xF57C00,
                "fields": [
                    {
                        "name": "1 day",
                        "value": (
                            f"**{today_row['d1']:,}**\n"
                            f"vs day before: {pct_change(today_row['d1'], prev_day['d1'])}\n"
                            f"vs last week: {pct_change(today_row['d1'], last_week['d1'])}"
                        ),
                        "inline": False,
                    },
                    {"name": "7 days", "value": f"{today_row['d7']:,}", "inline": True},
                    {"name": "28 days", "value": f"{today_row['d28']:,}", "inline": True},
                ],
                "footer": {"text": "Source: Google Analytics for Firebase"},
            }
        ],
    }


def post_to_discord(payload):
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Discord rejects the default Python user agent.
            "User-Agent": "dau-notifier/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Posted to Discord (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"Discord error {e.code}: {e.read().decode()}", file=sys.stderr)
        raise


if __name__ == "__main__":
    data = fetch_active_users()
    payload = build_message(data)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    post_to_discord(payload)
