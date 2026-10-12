"""Minimal PostHog query client (HogQL over the /query/ API). Standard library only."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config

RETRYABLE = {429, 500, 502, 503, 504}


class PostHogError(RuntimeError):
    pass


class Client:
    def __init__(self, api_key: str, host: str = config.POSTHOG_HOST, project_id: str = config.POSTHOG_PROJECT_ID):
        if not api_key:
            raise PostHogError("POSTHOG_API_KEY is empty.")
        self.url = f"{host}/api/projects/{project_id}/query/"
        self.api_key = api_key

    def run(self, query: str) -> list[dict]:
        """Run one HogQL query and return its rows as dicts keyed by column name."""
        body = json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode()
        for attempt in range(4):
            request = urllib.request.Request(self.url, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": config.USER_AGENT,
            })
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = json.load(response)
                return [dict(zip(data["columns"], row)) for row in data["results"]]
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace")[:400]
                if err.code in RETRYABLE and attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise PostHogError(f"PostHog query failed with HTTP {err.code}: {detail}") from None
            except urllib.error.URLError as err:
                if attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise PostHogError(f"Couldn't reach PostHog: {err.reason}") from None
        raise PostHogError("PostHog query failed after retries.")
