"""PNG charts drawn on the GitHub runner with matplotlib. No data goes to an outside chart service.

Labels are English only. Text and plan titles (Tibetan, Chinese, ...) stay in the Discord message,
where Discord renders every script, so the runner needs no extra fonts.
"""
from __future__ import annotations

import datetime as dt
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from . import config  # noqa: E402
from .text import d, live_days, range_label  # noqa: E402

# Discord's dark embed background, so each chart sits flush inside its embed card.
BG, FG, MUTED, GRID = "#2B2D31", "#F2F3F5", "#B5BAC1", "#3F4147"
NEW, RETURNING, PREV = "#F0A73A", "#3FB8AF", "#80848E"
DARK_TEXT = "#1E1F22"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": GRID, "font.family": "DejaVu Sans", "font.size": 12,
    "axes.labelsize": 12, "xtick.labelsize": 12, "ytick.labelsize": 12, "legend.fontsize": 12,
})

W, H, DPI = 6.4, 4.0, 200  # 1280 x 800 px: text stays legible when Discord shows it ~400-500 px wide

ACTIVITY_LABELS = [("read", "Read a text"), ("plan_open", "Opened a plan"), ("live", "Joined live session"),
                   ("mala", "Used mala counter"), ("plan_day", "Finished plan day"), ("timer", "Finished timer")]
FUNNEL_STEPS = ["Opened the app\nfor the first time", "Signed in or\ncontinued as guest",
                "Finished the\nwelcome setup", "Read or practised\non day one"]


def _thousands(x, _pos=None):
    return f"{int(x):,}"


def _day_month(x, _pos=None):
    day = mdates.num2date(x)
    return f"{day.day} {day:%b}"


def _frame(ax, title: str, subtitle: str):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0, pad=6)
    ax.set_axisbelow(True)
    fig = ax.figure
    fig.text(0.03, 0.955, title, fontsize=15.5, fontweight="bold", color=FG, va="top")
    fig.text(0.03, 0.88, subtitle, fontsize=11.5, color=MUTED, va="top")


def _legend(ax, order: list[str], anchor_x: float, ncol: int, **kw):
    handles, labels = ax.get_legend_handles_labels()
    pick = [labels.index(x) for x in order if x in labels]
    ax.legend([handles[k] for k in pick], [labels[k] for k in pick], loc="lower left",
              bbox_to_anchor=(anchor_x, 1.0), ncol=ncol, frameon=False, handlelength=1.4,
              columnspacing=1.4, labelcolor=FG, **kw)


def daily_people_week(path, dates, people, new, prev_people, prev_label, subtitle):
    """This week as stacked bars (used it before + new), the week before as a dashed line by weekday."""
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.subplots_adjust(left=0.13, right=0.98, top=0.72, bottom=0.19)
    x = list(range(len(dates)))
    before = [p - k for p, k in zip(people, new)]
    ax.bar(x, before, width=0.64, color=RETURNING, label="Used it before")
    ax.bar(x, new, width=0.64, bottom=before, color=NEW, label="New")
    ax.plot(list(range(len(prev_people))), prev_people, color=PREV, lw=2, ls=(0, (4, 3)), marker="o", ms=6,
            label=prev_label)
    top = max(max(people, default=0), max(prev_people, default=0), 1)
    for xi, p in zip(x, people):
        ax.text(xi, p + top * 0.02, _thousands(p), ha="center", va="bottom", fontsize=11, fontweight="bold",
                color=FG)
    ax.set_xticks(x, [f"{day:%a}\n{day.day} {day:%b}" for day in map(d, dates)])
    ax.set_xlim(-0.6, 6.6)
    ax.set_ylim(0, top * 1.15)
    ax.yaxis.set_major_locator(MaxNLocator(5, integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_ylabel("People")
    ax.set_xlabel("Day")
    _frame(ax, "People who opened the app each day", subtitle)
    _legend(ax, ["Used it before", "New", prev_label], -0.01, 3)
    fig.savefig(path)
    plt.close(fig)


def daily_people_months(path, prev_dates, prev_people, cur_dates, cur_people, cur_new, prev_label, subtitle,
                        marker=None):
    """The previous month as a grey line and this month as stacked bars, on one timeline."""
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.subplots_adjust(left=0.13, right=0.98, top=0.72, bottom=0.16)
    pdays, cdays = list(map(d, prev_dates)), list(map(d, cur_dates))
    before = [p - k for p, k in zip(cur_people, cur_new)]
    ax.plot(pdays, prev_people, color=PREV, lw=2.2, label=prev_label)
    ax.bar(cdays, before, width=0.78, color=RETURNING, label="Used it before")
    ax.bar(cdays, cur_new, width=0.78, bottom=before, color=NEW, label="New")
    top = max(max(prev_people, default=0), max(cur_people, default=0), 1)
    if marker:
        ax.axvline(marker[0], color=MUTED, lw=1, ls=(0, (2, 3)))
        ax.text(marker[0], top * 1.04, f"{marker[1]} ", color=MUTED, fontsize=11, ha="right", va="bottom")
    ax.set_ylim(0, top * 1.18)
    ax.set_xlim(mdates.date2num(pdays[0]) - 0.6, mdates.date2num(cdays[-1]) + 0.6)
    ax.yaxis.set_major_locator(MaxNLocator(5, integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(FuncFormatter(_day_month))
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_ylabel("People")
    ax.set_xlabel("Day (ticks on Mondays)")
    _frame(ax, "People who opened the app each day", subtitle)
    _legend(ax, ["Used it before", "New", prev_label], -0.01, 3)
    fig.savefig(path)
    plt.close(fig)


def activities(path, labels, cur, prev, cur_label, prev_label, subtitle):
    """People per activity, this period vs the previous one."""
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.subplots_adjust(left=0.335, right=0.94, top=0.72, bottom=0.15)
    y = list(range(len(labels)))
    h = 0.38
    ax.barh([v - h / 2 for v in y], cur, height=h, color=NEW, label=cur_label)
    ax.barh([v + h / 2 for v in y], prev, height=h, color=PREV, label=prev_label)
    top = max(max(cur), max(prev), 1)
    for v, c in zip(y, cur):
        ax.text(c + top * 0.012, v - h / 2, _thousands(c), va="center", fontsize=11, fontweight="bold", color=FG)
    for v, c in zip(y, prev):
        ax.text(c + top * 0.012, v + h / 2, _thousands(c), va="center", fontsize=10.5, color=MUTED)
    ax.set_yticks(y, labels)
    ax.tick_params(axis="y", labelcolor=FG, labelsize=12)
    ax.invert_yaxis()
    ax.set_xlim(0, top * 1.14)
    ax.xaxis.set_major_locator(MaxNLocator(5, integer=True))
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.grid(axis="x", color=GRID, lw=1)
    ax.set_xlabel("People (each person counted once per activity)")
    ax.set_ylabel("Activity")
    _frame(ax, "What people did in the app", subtitle)
    _legend(ax, [cur_label, prev_label], -0.49, 2)
    fig.savefig(path)
    plt.close(fig)


def funnel(path, steps, cur, prev, cur_label, prev_label, subtitle):
    """Share of new installs reaching each step; the previous period as a white tick for comparison."""
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.subplots_adjust(left=0.335, right=0.94, top=0.72, bottom=0.15)
    y = list(range(len(steps)))
    cur_pct = [c / cur[0] * 100 for c in cur]
    ax.barh(y, cur_pct, height=0.6, color=NEW, label=cur_label)
    if prev[0]:
        ax.scatter([c / prev[0] * 100 for c in prev], y, marker="|", s=900, linewidths=3, color=FG, zorder=3,
                   label=prev_label)
    for v, p, c in zip(y, cur_pct, cur):
        inside = p > 30
        ax.text(p - 1.5 if inside else p + 1.5, v, f"{p:.0f}%  ({_thousands(c)})", va="center",
                ha="right" if inside else "left", fontsize=11.5, fontweight="bold",
                color=DARK_TEXT if inside else FG)
    ax.set_yticks(y, steps)
    ax.tick_params(axis="y", labelcolor=FG, labelsize=12)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _p: f"{x:.0f}%"))
    ax.grid(axis="x", color=GRID, lw=1)
    ax.set_xlabel("Share of people who installed the app")
    ax.set_ylabel("Step")
    _frame(ax, "From install to first practice", subtitle)
    _legend(ax, [cur_label, prev_label], -0.49, 2, scatterpoints=1, markerscale=0.5)
    fig.savefig(path)
    plt.close(fig)


def period_charts(kind: str, cur: dict, prev: dict, outdir: str,
                  tracking_start: dt.date = config.TRACKING_START) -> list[tuple[str, str]]:
    """Draw the three charts for a weekly or monthly report. Returns [(filename, alt text)] in embed order."""
    weekly = kind == "weekly"
    start, end, pstart = d(cur["start"]), d(cur["end"]), d(prev["start"])
    preview = cur.get("preview", False)
    partial = pstart < tracking_start
    pdays = live_days(prev, tracking_start)
    out: list[tuple[str, str]] = []

    if weekly:
        prev_name = "launch week" if partial else "last week"
        prev_label = prev_name.capitalize()
        span = range_label(start, end) + (" (so far)" if preview else "")
        cur_label, new_label, when = "This week", "New this week", "this week" + (" so far" if preview else "")
        people_sub = f"{span} · grey line = {prev_name}"
        if partial:
            people_sub += f" (live from {tracking_start.day} {tracking_start:%b})"
    else:
        month, prev_label = f"{start:%B}", f"{pstart:%B}"
        prev_name = prev_label
        cur_label = month + (f" (1–{end.day})" if preview else "")
        new_label, when = f"New in {month}", f"in {month}" + (" so far" if preview else "")
        span = f"{month} so far" if preview else month
        people_sub = (f"{month} so far (1–{end.day} {end:%b})" if preview else month) + \
            f" as bars · {prev_label} as a grey line"

    name = f"{kind}-people.png"
    if weekly:
        daily_people_week(os.path.join(outdir, name), cur["daily_dates"], cur["daily_people"], cur["daily_new"],
                          prev["daily_people"], prev_label, people_sub)
        alt = (f"Bar chart: people who opened the app each day, {range_label(start, end)}, split into new and "
               f"returning, with {prev_name} as a dashed line.")
    else:
        marker = None
        if pstart < tracking_start <= end:
            marker = (tracking_start, f"Launch, {tracking_start.day} {tracking_start:%b}")
        daily_people_months(os.path.join(outdir, name), prev["daily_dates"], prev["daily_people"],
                            cur["daily_dates"], cur["daily_people"], cur["daily_new"], prev_label, people_sub,
                            marker)
        alt = (f"Chart: people who opened the app each day; {month} as bars split into new and returning, "
               f"{prev_label} as a grey line.")
    out.append((name, alt))

    name = f"{kind}-activities.png"
    sub = f"People per activity, {span} vs {prev_name}" + (f" ({pdays} live days)" if partial else "")
    activities(os.path.join(outdir, name), [label for _, label in ACTIVITY_LABELS],
               [cur["activities"][k] for k, _ in ACTIVITY_LABELS], [prev["activities"][k] for k, _ in ACTIVITY_LABELS],
               cur_label, prev_label, sub)
    out.append((name, f"Bar chart: people per activity, {span} compared with {prev_name}."))

    if cur["funnel"][0]:
        name = f"{kind}-funnel.png"
        sub = f"{cur['funnel'][0]:,} people installed the app {when} · within one day of installing"
        funnel(os.path.join(outdir, name), FUNNEL_STEPS, cur["funnel"], prev["funnel"], new_label, prev_label, sub)
        out.append((name, "Funnel chart: share of new installs who signed in, finished setup and read or "
                          f"practised on day one, compared with {prev_name}."))
    return out
