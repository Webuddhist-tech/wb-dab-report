"""Plain-language Discord messages built from aggregate numbers (counts of people, medians, shares)."""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from statistics import mean

from . import config

RED, GREEN, NEUTRAL = 0xED4245, 0x57F287, 0x5865F2
WEEKLY_COLOR, MONTHLY_COLOR = 0xF0A73A, 0x3FB8AF

UP, DOWN, ABOUT = "▲", "▼", "≈"
FLAT_PCT = 3       # changes smaller than this many percent are shown as "≈"
MAX_TITLE = 60     # characters, for text and plan titles
NO_PINGS = {"parse": []}  # titles come from content; never let one ping @everyone
LINK = re.compile(r"://|www\.|discord\.gg|discord(?:app)?\.com/invite", re.IGNORECASE)

LANGUAGE_NAMES = {"bo": "Tibetan", "en": "English", "zh": "Chinese", "hi": "Hindi", "pi": "Pali", "ne": "Nepali"}
MAIN_LANGUAGES = ("en", "bo", "zh")

# Airbridge's keys for the channels people ask about. Others are shown as Airbridge names them.
CHANNEL_NAMES = {"unattributed": "Organic", "google.adwords": "Google Ads", "$$default$$": "Links without a channel"}
EXTRAS_COLOR = 0x99AAB5


# ---------- formatting ----------

def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def n(x: float) -> str:
    return f"{int(round(x)):,}"


def _round_secs(secs: float) -> int:
    """Round a duration to what people can picture: 5 seconds, half a minute, a minute or 5 minutes."""
    s = max(0, int(round(secs)))
    step = 5 if s < 60 else 30 if s < 600 else 60 if s < 3600 else 300
    return int(round(s / step)) * step


def minutes(secs: float) -> str:
    """'45 sec', '4½ min', '12 min', '1 h 20 min'."""
    s = _round_secs(secs)
    if s < 60:
        return f"{s} sec"
    if s < 3600:
        m, half = divmod(s, 60)
        return f"{m}{'½' if half else ''} min"
    h, m = divmod(s // 60, 60)
    return f"{h} h {m} min" if m else f"{h} h"


def time_change(cur: float, prev: float | None, against: str) -> str:
    """'▲ 30 sec more than Sat (3½ min)'. Worked out from the rounded figures, so it matches what's shown."""
    if not prev:
        return f"no {against} to compare"
    a, b = _round_secs(cur), _round_secs(prev)
    if a == b:
        return f"{ABOUT} same as {against} ({minutes(prev)})"
    return f"{UP if a > b else DOWN} {minutes(abs(a - b))} {'more' if a > b else 'less'} than {against} ({minutes(prev)})"


def time_spread(spread: dict) -> str:
    """'30% closed it within a minute · 20% stayed half an hour or more', or '' with no data."""
    people = spread["timed_people"]
    if not people:
        return ""
    return (f"{pct(spread['quick_people'], people)} closed it within a minute · "
            f"{pct(spread['long_people'], people)} stayed half an hour or more")


def pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "–"


def day_label(day: dt.date) -> str:  # "Thu 8 Oct"
    return f"{day:%a} {day.day} {day:%b}"


def range_label(start: dt.date, end: dt.date) -> str:  # "28 Sep – 4 Oct"
    if start.month == end.month:
        return f"{start.day} – {end.day} {end:%b}"
    return f"{start.day} {start:%b} – {end.day} {end:%b}"


def ordinal(k: int) -> str:
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def change(cur: float, prev: float | None, against: str, fmt=n) -> str:
    """'▼ 8% vs Wed (611)', or '≈ 7-day avg (9m 27s)' when the move is small."""
    if not prev:
        return f"no {against} to compare"
    p = (cur - prev) / prev * 100
    if abs(p) < FLAT_PCT:
        return f"{ABOUT} {against} ({fmt(prev)})"
    return f"{UP if p > 0 else DOWN} {abs(p):.0f}% vs {against} ({fmt(prev)})"


def sign(x: float) -> int:
    return (x > 0) - (x < 0)


def md(text: str) -> str:
    """Escape Discord markdown in data, so a title can't turn into bold text, a link or a quote."""
    return "".join("\\" + ch if ch in "\\*_~`|<>[]" else ch for ch in text)


def short(title: str, limit: int = MAX_TITLE) -> str:
    """Shorten a title without breaking a Tibetan stack or an Indic conjunct.

    Cutting by code points can separate a base letter from its vowel signs or subjoined letters,
    so the cut moves back until it sits before a base letter, preferring a tsheg or a space.
    """
    title = " ".join(title.split())
    if len(title) <= limit:
        return title
    cut = limit - 1
    while cut > 0 and (unicodedata.category(title[cut]).startswith("M")
                       or "VIRAMA" in unicodedata.name(title[cut - 1], "")
                       or title[cut - 1] in "‌‍"):
        cut -= 1
    for k in range(cut, max(cut - 15, 0), -1):
        if title[k - 1] in " ་།":  # space, tsheg, shad
            cut = k
            break
    return title[:cut].rstrip(" ,·-") + "…"


def title(t: str) -> str:
    # Titles come from app events, and anyone can send events to PostHog, so never show a link.
    if LINK.search(t):
        return "(title hidden: it contained a link)"
    return md(short(t))


def lang_name(code: str) -> str:
    """Name for a language code from app events. Anything that isn't a plain code shows as unknown."""
    if code in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[code]
    return code if re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", code or "") else "unknown"


# ---------- daily ----------

def what_changed(s: dict) -> str:
    """One sentence on what moved on the report day and the most likely driver, from aggregate signals only."""
    i = len(s["people"]) - 1
    cur, prev = s["people"][i], s["people"][i - 1]
    delta = cur - prev
    prev_day = f"{d(s['dates'][i - 1]):%A}"

    if abs(delta) < max(10, 0.03 * prev):
        return f"about the same number of people as {prev_day}; nothing stands out."

    streak, j = 0, i
    while j > 0 and sign(s["people"][j] - s["people"][j - 1]) == sign(delta):
        streak, j = streak + 1, j - 1
    word = "rise" if delta > 0 else "drop"
    head = (f"the {ordinal(streak)} daily {word} in a row" if streak >= 3
            else f"{'more' if delta > 0 else 'fewer'} people than {prev_day} ({n(prev)} → {n(cur)})")

    # Where: one platform carrying the change while the other held steady.
    where = ""
    da = s["android"][i] - s["android"][i - 1]
    dp = s["apple"][i] - s["apple"][i - 1]

    def steady(x, base):
        return abs(x) <= max(10, 0.05 * base)

    if sign(da) == sign(delta) and abs(da) >= 0.7 * abs(delta) and steady(dp, s["apple"][i - 1]):
        where = f"almost all on Android ({n(s['android'][i - 1])} → {n(s['android'][i])}; iPhone & iPad steady)"
    elif sign(dp) == sign(delta) and abs(dp) >= 0.7 * abs(delta) and steady(da, s["android"][i - 1]):
        where = f"almost all on iPhone & iPad ({n(s['apple'][i - 1])} → {n(s['apple'][i])}; Android steady)"

    # Why: the signal that moved the same way and accounts for the largest share of the change.
    causes = []
    for key, more, fewer, min_abs in (
        ("push_open_people", "more people opened the app from a notification",
         "fewer people opened the app from a notification", 15),
        ("live_people", "more people joined a live session", "fewer people joined a live session", 20),
        ("new", "more first-time people", "fewer first-time people", 15),
    ):
        dx = s[key][i] - s[key][i - 1]
        if sign(dx) == sign(delta) and abs(dx) >= min_abs and abs(dx) >= 0.25 * abs(delta):
            causes.append((abs(dx) / abs(delta), f"{more if dx > 0 else fewer} ({n(s[key][i - 1])} → {n(s[key][i])})"))
    causes.sort(key=lambda c: -c[0])

    sentence = ", ".join([head] + ([where] if where else []))
    if causes:
        share, why = causes[0]
        sentence += f", {'likely' if share >= 0.5 else 'partly'} because {why}"
    elif not where:
        sentence += "; no single platform or activity stands out"
    return sentence + "."


def daily_payload(s: dict, dashboard_url: str = config.DASHBOARD_URL, extras: dict | None = None) -> dict:
    i = len(s["people"]) - 1
    day, prev_day = d(s["dates"][i]), d(s["dates"][i - 1])
    vs_prev = f"{prev_day:%a}"
    week = slice(i - 7, i)  # the 7 days before the report day

    def line(emoji, label, key, fmt=n):
        cur, prev, avg = s[key][i], s[key][i - 1], mean(s[key][week])
        return (f"{emoji} **{fmt(cur)}** {label}\n"
                f"{change(cur, prev, vs_prev, fmt)} · {change(cur, avg, '7-day avg', fmt)}")

    lines = []
    if s["people"][i] == 0:
        lines.append("⚠️ **No app activity was recorded for this day.** Data may not have reached PostHog.")
    def time_line():
        cur, prev, avg = s["typical_secs"][i], s["typical_secs"][i - 1], mean(s["typical_secs"][week])
        text = (f"⏱️ Half of people had the app on screen for **{minutes(cur)}** or more\n"
                f"{time_change(cur, prev, vs_prev)} · {time_change(cur, avg, 'the 7-day average')}")
        spread = time_spread({k: s[k][i] for k in ("timed_people", "quick_people", "long_people")})
        return text + (f"\n{spread}" if spread else "")

    lines += [
        line("👥", "people opened the app", "people"),
        line("🌱", "people opened the app for the first time", "new"),
        line("📖", "people read a text", "readers"),
        time_line(),
        f"**What changed:** {what_changed(s)}",
    ]
    avg_people = mean(s["people"][week])
    ratio = s["people"][i] / avg_people - 1 if avg_people else 0
    color = RED if ratio <= -0.05 else GREEN if ratio >= 0.05 else NEUTRAL

    embeds = [{
        "title": f"📱 WeBuddhist app · {day_label(day)}",
        "url": dashboard_url,
        "color": color,
        "description": "\n\n".join(lines),
        "footer": {"text": "Mobile app (iPhone, iPad, Android) · A day runs 5:30 AM–5:30 AM IST · "
                           "Time counts only while the app is on screen"},
    }]
    more = extras_embed(extras, "daily")
    if more:
        embeds.append(more)
    return {"username": config.BOT_NAME, "allowed_mentions": NO_PINGS, "embeds": embeds}


# ---------- weekly / monthly ----------

def live_days(p: dict, tracking_start: dt.date) -> int:
    return sum(1 for x in p["daily_dates"] if d(x) >= tracking_start)


def avg_per_day(p: dict, tracking_start: dt.date) -> float:
    vals = [v for x, v in zip(p["daily_dates"], p["daily_people"]) if d(x) >= tracking_start]
    return sum(vals) / len(vals) if vals else 0


def _lang_line(langs: dict) -> str:
    total = sum(langs.values())
    if not total:
        return "no reading yet"
    main = sorted(((k, v) for k, v in langs.items() if k in MAIN_LANGUAGES), key=lambda kv: -kv[1])
    other = total - sum(v for _, v in main)
    parts = [f"{LANGUAGE_NAMES[k]} {pct(v, total)}" for k, v in main]
    if other:
        parts.append(f"other {pct(other, total)}")
    return " · ".join(parts)


def period_payload(kind: str, cur: dict, prev: dict, tracking_start: dt.date = config.TRACKING_START,
                   dashboard_url: str = config.DASHBOARD_URL, charts: list[tuple[str, str]] = (),
                   extras: dict | None = None, footer_note: str = "") -> dict:
    """kind: 'weekly' or 'monthly'. charts: [(filename, alt text)], one per section, in order.

    extras: what extras.collect() returned. footer_note: a line added to the report's footer.
    """
    weekly = kind == "weekly"
    start, end = d(cur["start"]), d(cur["end"])
    preview = cur.get("preview", False)

    # A previous period that started before tracking did is only partly covered: show its totals
    # side by side and compare per-day figures only.
    prev_partial = d(prev["start"]) < tracking_start
    prev_days = live_days(prev, tracking_start)
    if weekly:
        prev_name = "launch week" if prev_partial else "last week"
    else:
        prev_name = f"{d(prev['start']):%B}"
    newcomers = f"{prev_name}'s"

    def vs_total(a, b):
        if prev_partial:
            return f"{prev_name}: {n(b)} ({prev_days} days live)" if prev_days else f"{prev_name}: no data yet"
        return change(a, b, prev_name)

    def vs(a, b, fmt=n):
        if prev_partial and not prev_days:
            return f"no data for {prev_name}"
        return change(a, b, prev_name, fmt)

    avg_cur, avg_prev = avg_per_day(cur, tracking_start), avg_per_day(prev, tracking_start)
    a, pa = cur["activities"], prev["activities"]
    f, pf = cur["funnel"], prev["funnel"]
    plat, pplat = cur["platform"], prev["platform"]
    cb = cur.get("came_back")

    # --- three-line summary ---
    if prev_partial:
        line1 = f"**{n(cur['people'])} people** used the app — about {n(avg_cur)} a day"
        if avg_prev:
            line1 += (f", {'up' if avg_cur >= avg_prev else 'down'} {abs(avg_cur / avg_prev - 1) * 100:.0f}% "
                      f"from {prev_name}'s {n(avg_prev)} a day")
        line1 += "."
    elif prev["people"]:
        p = cur["people"] / prev["people"] - 1
        line1 = (f"**{n(cur['people'])} people** used the app, {'up' if p >= 0 else 'down'} "
                 f"{abs(p) * 100:.0f}% from {prev_name} ({n(prev['people'])}).")
    else:
        line1 = f"**{n(cur['people'])} people** used the app."
    line2 = f"**{n(cur['new'])} were new**"
    if cb:
        line2 += (f", and **{pct(cb['back'], cb['cohort'])}** of {newcomers} newcomers came back "
                  f"({n(cb['back'])} of {n(cb['cohort'])})")
    line2 += "."
    acts = {"reading": a["read"], "live sessions": a["live"], "plans": a["plan_open"], "the mala counter": a["mala"]}
    top_act = max(acts, key=acts.get)
    top_text = cur["top_texts"][0] if cur.get("top_texts") else None
    if top_act == "reading" and top_text:
        line3 = f"Most popular: **reading** ({n(a['read'])} people), led by “{title(top_text[0])}” ({n(top_text[2])})."
    elif top_text:
        line3 = (f"Most popular: **{top_act}** ({n(acts[top_act])} people); most-read text: "
                 f"“{title(top_text[0])}” ({n(top_text[2])}).")
    else:
        line3 = f"Most popular: **{top_act}** ({n(acts[top_act])} people)."

    if weekly:
        header = f"**📅 Weekly report · {day_label(start)} – {day_label(end)}{' (so far)' if preview else ''}**"
    elif preview:
        header = f"**🗓️ Monthly report · {start:%B} (1–{end.day} so far)**"
    else:
        header = f"**🗓️ Monthly report · {start:%B %Y}**"
    content = "\n".join([header, f"• {line1}", f"• {line2}", f"• {line3}"])

    # --- People ---
    people_lines = [
        f"**{n(cur['people'])}** people used the app · {vs_total(cur['people'], prev['people'])}",
        f"**{n(avg_cur)}** a day on average · {vs(avg_cur, avg_prev)}",
        f"**{n(cur['new'])}** new · **{n(cur['people'] - cur['new'])}** had used it before",
    ]
    if cb:
        people_lines.append(f"**{pct(cb['back'], cb['cohort'])}** of {newcomers} newcomers came back "
                            f"({n(cb['back'])} of {n(cb['cohort'])})")
    time_vs = (f"no data for {prev_name}" if prev_partial and not prev_days
               else time_change(cur["typical_secs"], prev["typical_secs"], prev_name))
    people_lines.append(f"Half of people had the app on screen for **{minutes(cur['typical_secs'])}** or more a day · "
                        f"{time_vs}")
    spread = time_spread(cur["time_spread"])
    if spread:
        people_lines.append(f"Each day, {spread}")

    # --- What people did ---
    did_lines = [
        f"**{n(a['read'])}** read a text · {vs_total(a['read'], pa['read'])}",
        f"**{n(a['live'])}** joined a live session · {vs_total(a['live'], pa['live'])}",
        f"**{n(a['plan_open'])}** opened a plan · {n(a['plan_day'])} finished at least one plan day",
        f"**{n(a['mala'])}** used the mala counter · {n(a['mala_rounds'])} rounds completed",
        f"**{n(a['timer'])}** finished a meditation timer",
    ]
    if cur.get("top_texts"):
        did_lines += ["", "**Most-read texts** (people)"]
        did_lines += [f"{k}. {title(t)} · {lang_name(lang)} · {n(c)}"
                      for k, (t, lang, c) in enumerate(cur["top_texts"], 1)]
    if cur.get("top_plans"):
        did_lines += ["", "**Most-opened plans** (opened · finished a day)"]
        did_lines += [f"{k}. {title(t)} · {n(o)} · {n(c)}" for k, (t, o, c) in enumerate(cur["top_plans"], 1)]

    # --- Phones, language and sign-up ---
    tot, ptot = sum(plat.values()), sum(pplat.values())
    sign_lines = [
        f"**Phones:** Android {pct(plat['Android'], tot)} · iPhone & iPad {pct(plat['iPhone & iPad'], tot)}"
        + (f" ({prev_name}: {pct(pplat['Android'], ptot)} · {pct(pplat['iPhone & iPad'], ptot)})" if ptot else ""),
        f"**Main reading language:** {_lang_line(cur['languages'])}",
    ]
    if sum(prev["languages"].values()):
        sign_lines.append(f"{prev_name[0].upper() + prev_name[1:]}: {_lang_line(prev['languages'])}")
    sign_lines += ["", "**New people, from install to first practice**"]
    if f[0]:
        steps = ["opened the app for the first time", "signed in or continued as a guest",
                 "finished the welcome setup", "read or practised on day one"]
        sign_lines.append(f"{n(f[0])} {steps[0]}")
        for k in range(1, 4):
            before = f" ({prev_name} {pct(pf[k], pf[0])})" if pf[0] else ""
            sign_lines.append(f"→ {pct(f[k], f[0])} {steps[k]}{before}")
        drops = [(f[k - 1] - f[k]) / f[0] for k in range(1, 4)]
        worst = max(range(3), key=lambda k: drops[k])
        where = ["before signing in", "during the welcome setup", "after setup, without reading or practising"][worst]
        tenths = round(drops[worst] * 10)
        sign_lines.append(f"Biggest drop: **{'about ' + str(tenths) if tenths else 'under 1'} in 10 left {where}.**")
    else:
        sign_lines.append("No new installs in this period.")

    span = "Mon–Sun weeks" if weekly else "Calendar months"
    footer = (f"Mobile app · {span}; a day runs 5:30 AM–5:30 AM IST · Counts are people, not visits · "
              "Time counts only while the app is on screen") + (f" · {footer_note}" if footer_note else "")

    color = WEEKLY_COLOR if weekly else MONTHLY_COLOR
    sections = [("👥 People", people_lines), ("📖 What people did", did_lines),
                ("📱 Phones, language and sign-up", sign_lines)]
    embeds = []
    for k, (heading, body) in enumerate(sections):
        embed = {"title": heading, "color": color, "description": "\n".join(body)}
        if k == 0:
            embed["url"] = dashboard_url
        if k < len(charts):
            embed["image"] = {"url": f"attachment://{charts[k][0]}"}
        embeds.append(embed)
    embeds[-1]["footer"] = {"text": footer}
    more = extras_embed(extras, kind, prev_name)
    if more:
        embeds.append(more)

    payload = {"username": config.BOT_NAME, "allowed_mentions": NO_PINGS, "content": content, "embeds": embeds}
    if charts:
        payload["attachments"] = [{"id": k, "filename": fn, "description": alt} for k, (fn, alt) in enumerate(charts)]
    return payload


# ---------- other sources: Airbridge, Firebase, Clarity ----------

def pct1(x: float) -> str:
    """'99.4%'. Rounded down, so a day with any crash never shows as 100%."""
    return f"{math.floor(x * 10) / 10:.1f}%".replace(".0%", "%")


def points(cur: float | None, prev: float | None, against: str) -> str:
    """Change in a percentage, in points: '▲ 0.3 points vs Sat (99.1%)'."""
    if cur is None or prev is None:
        return f"no {against} to compare"
    diff = cur - prev
    if abs(diff) < 0.1:
        return f"{ABOUT} {against} ({pct1(prev)})"
    return f"{UP if diff > 0 else DOWN} {abs(diff):.1f} points vs {against} ({pct1(prev)})"


def _crash_free(block: dict) -> float | None:
    return 100 * (1 - block["crashed"] / block["active"]) if block["active"] else None


def _channel(key: str) -> str:
    # Channel names come from tracking links, which anyone can make up, so they go through title().
    return CHANNEL_NAMES.get(key) or title(key or "unknown")


def installs_lines(x: dict, against: str) -> list[str]:
    rows = sorted((r for r in x["channels"] if r["installs"] > 0), key=lambda r: -r["installs"])
    total = sum(r["installs"] for r in rows)
    if not total:
        return [f"📥 **No installs** recorded by Airbridge · {against}: {n(x['prev_total'])}"]
    parts = [f"{_channel(r['channel'])} {pct(r['installs'], total)}" for r in rows[:3]]
    rest = total - sum(r["installs"] for r in rows[:3])
    if rest:
        parts.append(f"other {pct(rest, total)}")
    masked = " (Meta rounds some counts down)" if any(r["masked"] for r in rows) else ""
    return [f"📥 **{n(total)} installs** · {change(total, x['prev_total'], against)}",
            "Came from: " + " · ".join(parts) + masked]


def crash_lines(c: dict, when: str, against: str) -> list[str]:
    cur = c["cur"]
    platforms = [f"{name} {pct1(100 * (1 - k / a))}" for name, (a, k) in cur["by_platform"].items() if a]
    detail = f"{n(cur['crashed'])} of {n(cur['active'])} people had the app crash"
    if len(platforms) > 1:
        detail += " · " + " · ".join(platforms)
    when = f" {when}" if when else ""
    return [f"🛟 **{pct1(_crash_free(cur))} crash-free**{when} · {points(_crash_free(cur), _crash_free(c['prev']), against)}",
            detail]


def notification_lines(x: dict, when: str, against: str | None) -> list[str]:
    days = x["days"]
    sent = sum(day["accepted"] for day in days)
    share = {k: sum(day[k] * day["accepted"] for day in days) / sent for k in ("delivered", "pending", "dropped")}
    head = f"🔔 **{share['delivered']:.0f}% of notifications reached** Android phones {when}"
    if x.get("prev"):
        head += f" · {points(share['delivered'], x['prev']['delivered'], against)}"
    return [head, f"{share['pending']:.0f}% waiting for phones that were offline · {share['dropped']:.0f}% dropped · "
                  f"measured on {n(sent)} messages"]


def website_lines(w: dict) -> list[str]:
    head = f"🌐 **{n(w['visits'])} website visits** in the last 24 hours"
    if w["pages_per_visit"] is not None:
        head += f" · {w['pages_per_visit']:.1f} pages per visit"
    if w["active_secs"] is not None:
        head += f" · {minutes(w['active_secs'])} active per visit"
    issues = [(label, w["issues"].get(key)) for key, label in
              (("rage_clicks", "rage clicks"), ("dead_clicks", "clicks that did nothing"), ("script_errors", "page errors"))]
    issues = " · ".join(f"{label} in {v:.0f}% of visits" for label, v in issues if v is not None)
    return [head] + ([issues[0].upper() + issues[1:]] if issues else [])


def extras_embed(x: dict | None, kind: str, prev_name: str = "") -> dict | None:
    """One embed with whatever the optional sources returned, or None when none are set up."""
    if not x:
        return None
    blocks, sources, footer = [], [], []
    daily = kind == "daily"
    if x.get("installs"):
        i = x["installs"]
        against = f"{d(i['start']) - dt.timedelta(days=1):%a}" if daily else prev_name
        blocks.append(installs_lines(i, against))
        sources.append("Installs")
        footer.append(f"Installs: Airbridge, days in {i['timezone']}")
    if x.get("crashes"):
        c = x["crashes"]
        start, end = d(c["start"]), d(c["end"])
        if daily:
            when, against = f"on {day_label(start)}", f"{start - dt.timedelta(days=1):%a}"
        else:
            when, against = (f"({range_label(start, end)})" if c.get("partial") else ""), prev_name
        blocks.append(crash_lines(c, when, against))
        sources.append("crashes")
        footer.append("Crashes: Firebase Crashlytics, a day behind")
    if x.get("notifications"):
        days = x["notifications"]["days"]
        first, last = d(days[0]["date"]), d(days[-1]["date"])
        when = f"on {day_label(last)}" if daily else f"({range_label(first, last)})"
        prev = x["notifications"].get("prev")
        blocks.append(notification_lines(x["notifications"], when, f"{d(prev['date']):%a}" if prev else None))
        sources.append("notifications")
        footer.append("Notifications: Firebase, Android only, up to 5 days behind")
    if x.get("website"):
        blocks.append(website_lines(x["website"]))
        sources.append("website")
        footer.append(f"Website: Microsoft Clarity, 24 hours to {x['website']['fetched_at']} UTC")
    if x.get("notes"):
        blocks.append([f"⚠️ {note}" for note in x["notes"]])
    if not blocks:
        return None
    if not sources:
        heading = "Other sources"
    elif len(sources) == 1:
        heading = sources[0]
    else:
        heading = ", ".join(sources[:-1]) + " and " + sources[-1]
    embed = {"title": f"📥 {heading[0].upper() + heading[1:]}", "color": EXTRAS_COLOR,
             "description": "\n\n".join("\n".join(b) for b in blocks)}
    if footer:
        embed["footer"] = {"text": " · ".join(footer)}
    return embed


# ---------- Discord limits ----------

def check_limits(payload: dict) -> dict:
    """Character counts against Discord's documented limits; raises ValueError if a message wouldn't post."""
    content = len(payload.get("content", ""))
    total = 0
    for e in payload.get("embeds", []):
        if len(e.get("title", "")) > 256 or len(e.get("description", "")) > 4096:
            raise ValueError("An embed title or description is over Discord's limit.")
        total += len(e.get("title", "").strip()) + len(e.get("description", "").strip())
        total += len(e.get("footer", {}).get("text", "").strip())
        total += sum(len(x["name"].strip()) + len(x["value"].strip()) for x in e.get("fields", []))
    if content > 2000 or total > 6000 or len(payload.get("embeds", [])) > 10:
        raise ValueError(f"Message too long for Discord: {content} text characters, {total} embed characters.")
    return {"content_chars": content, "embed_chars": total, "embeds": len(payload.get("embeds", [])),
            "files": len(payload.get("attachments", []))}
