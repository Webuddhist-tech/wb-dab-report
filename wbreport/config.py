"""Settings shared by the daily, weekly and monthly reports.

Secrets (PostHog key, Discord webhooks) are read from the environment in __main__.py, never stored here.
"""
from __future__ import annotations

import datetime as dt
import os

POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com").rstrip("/")
POSTHOG_PROJECT_ID = os.environ.get("POSTHOG_PROJECT_ID", "449016")
DASHBOARD_URL = f"{POSTHOG_HOST}/project/{POSTHOG_PROJECT_ID}/dashboard/1652644"

# Lower bound when looking for someone's first-ever visit. The PostHog project was created on 1 Jun 2026.
HISTORY_START = dt.date(2026, 6, 1)

# First full day of mobile tracking (the app launch). A comparison period that starts before this date
# is only partly tracked, so the weekly and monthly reports compare per-day averages instead of totals.
TRACKING_START = dt.date(2026, 9, 25)

# Android package name and iOS bundle ID (the same for both). Crashlytics names its BigQuery tables after it.
APP_NAMESPACE = "org.pecha.app"

BOT_NAME = "Webuddhist analyzer"
USER_AGENT = "wb-dab-report (https://github.com/Webuddhist-tech/wb-dab-report, 2.0)"
