"""Posting to a Discord webhook, with chart images attached as files. Standard library only."""
from __future__ import annotations

import copy
import http.client
import json
import time
import urllib.error
import urllib.request
import uuid

from . import config

NO_CHARTS_NOTE = "Charts couldn't be attached this time."


class DiscordError(RuntimeError):
    pass


def multipart(payload: dict, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """Encode payload_json plus files[n] as multipart/form-data, the format Discord expects for uploads."""
    boundary = "wbreport-" + uuid.uuid4().hex
    parts = []

    def add(name: str, data: bytes, content_type: str, filename: str | None = None):
        disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        parts.append(f"--{boundary}\r\nContent-Disposition: {disposition}\r\nContent-Type: {content_type}\r\n\r\n"
                     .encode() + data + b"\r\n")

    add("payload_json", json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
    for i, (filename, data) in enumerate(files):
        add(f"files[{i}]", data, "image/png", filename)
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def without_charts(payload: dict) -> dict:
    """The same message with the images removed and a short note in the last footer."""
    plain = copy.deepcopy(payload)
    plain.pop("attachments", None)
    for embed in plain.get("embeds", []):
        embed.pop("image", None)
    if plain.get("embeds"):
        footer = plain["embeds"][-1].setdefault("footer", {"text": ""})
        footer["text"] = (footer["text"] + " · " if footer["text"] else "") + NO_CHARTS_NOTE
    return plain


def _send(url: str, payload: dict, files: list[tuple[str, bytes]]) -> None:
    target = url + ("&" if "?" in url else "?") + "wait=true"  # wait=true makes Discord report failures
    if files:
        body, content_type = multipart(payload, files)
    else:
        body, content_type = json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"
    for attempt in range(4):
        try:
            request = urllib.request.Request(target, data=body, method="POST", headers={
                "Content-Type": content_type, "User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
            return
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:300]
            if err.code == 429 and attempt < 3:
                try:
                    wait = float(json.loads(detail).get("retry_after", 2))
                except (ValueError, AttributeError):
                    wait = 2.0
                time.sleep(min(wait, 30) + 0.5)
                continue
            if err.code >= 500 and attempt < 3:
                time.sleep(3 * 2 ** attempt)
                continue
            raise DiscordError(f"Discord returned HTTP {err.code}: {detail}") from None
        except urllib.error.URLError as err:
            if attempt < 3:
                time.sleep(3 * 2 ** attempt)
                continue
            raise DiscordError(f"Couldn't reach Discord: {err.reason}") from None
        except (ValueError, http.client.InvalidURL):  # their messages repeat the address, token included
            raise DiscordError("The webhook address isn't a valid URL. Check the secret for spaces or line breaks.") from None


def send_report(url: str, payload: dict, files: list[tuple[str, bytes]]) -> bool:
    """Post the report. If Discord refuses the images, post the text on its own.

    Returns True when the charts went out with the message.
    """
    if not files:
        _send(url, payload, [])
        return False
    try:
        _send(url, payload, files)
        return True
    except DiscordError as err:
        print(f"::warning::Discord didn't accept the charts ({err}). Posting the text without them.")
        _send(url, without_charts(payload), [])
        return False
