"""JSON over HTTPS for the optional sources (Airbridge, Clarity, Google). Standard library only."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request

from . import config

RETRYABLE = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """A source couldn't be read. The message names the source and the HTTP status, never a token."""


def request_json(source: str, url: str, *, method: str = "GET", token: str | None = None,
                 body: dict | None = None, timeout: int = 60, attempts: int = 4):
    """Send one request and return the parsed JSON response, retrying on rate limits and server errors."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": config.USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:200]
            if err.code in RETRYABLE and attempt < attempts - 1:
                time.sleep(min(_retry_after(err), 30) if err.code == 429 else 3 * 2 ** attempt)
                continue
            raise SourceError(f"{source} returned HTTP {err.code}: {detail}") from None
        except urllib.error.URLError as err:
            if attempt < attempts - 1:
                time.sleep(3 * 2 ** attempt)
                continue
            raise SourceError(f"Couldn't reach {source}: {err.reason}") from None
        except (ValueError, http.client.HTTPException):  # bad JSON, or a URL with stray characters
            raise SourceError(f"{source} sent a response that isn't valid JSON, or the address is wrong.") from None
    raise SourceError(f"{source} didn't answer after {attempts} tries.")


def _retry_after(err: urllib.error.HTTPError) -> float:
    try:
        return float(err.headers.get("Retry-After", 5))
    except (TypeError, ValueError):
        return 5.0
