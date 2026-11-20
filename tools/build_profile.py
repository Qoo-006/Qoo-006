#!/usr/bin/env python3
"""Build the terminal-style SVG cards for the GitHub profile README.

Commits are counted from local git history (all branches, deduplicated by hash),
so private repositories and commits whose author e-mail is not linked to the
GitHub account are included. Commits are deduplicated by author time + subject
because repos split out with filter-repo carry the same commits under new hashes. Settings live in tools/config.local.json (not committed).

usage: python3 tools/build_profile.py [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CONFIG = Path(__file__).resolve().parent / "config.local.json"

# GitHub dark palette
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
DIM = "#8b949e"
# ATOLLS colors (taken from the logo): lapis #0054B4 -> sky #009CF0 -> teal #18CCC0
TEAL = "#18CCC0"
SKY = "#009CF0"
BLUE = "#58a6ff"
LEVELS = ["#161b22", "#0b3d80", "#0054b4", "#009cf0", "#18ccc0"]
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
WIDTH = 840


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------- data

def find_repos(roots: list[str], excludes: list[str]) -> list[Path]:
    ex = [Path(os.path.expanduser(e)).resolve() for e in excludes]
    found = []
    for r in roots:
        base = Path(os.path.expanduser(r))
        for dirpath, dirnames, filenames in os.walk(base):
            p = Path(dirpath)
            depth = len(p.relative_to(base).parts)
            if any(p.resolve() == e or e in p.resolve().parents for e in ex):
                dirnames[:] = []
                continue
            if ".git" in dirnames or ".git" in filenames:
                found.append(p)
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".build", "DerivedData", "Pods")]
            if depth >= 4:
                dirnames[:] = []
    return found


def collect_commits(cfg: dict, since: dt.date) -> Counter:
    emails = {e.lower() for e in cfg["author_emails"]}
    skip = tuple(cfg.get("exclude_subject_prefixes", []))
    seen: set[str] = set()
    per_day: Counter = Counter()
    for repo in find_repos(cfg["repo_roots"], cfg.get("exclude_paths", [])):
        try:
            out = subprocess.run(
                ["git", "-C", str(repo), "log", "--branches", "--remotes", "--tags",
                 f"--since={since.isoformat()}", "--date=format-local:%Y-%m-%d",
                 "--format=%aI%x09%ae%x09%ad%x09%s"],
                capture_output=True, text=True, timeout=120,
            ).stdout
        except subprocess.TimeoutExpired:
            continue
        for line in out.splitlines():
            parts = line.split("\t", 3)
            if len(parts) < 4:
                continue
            stamp, email, day, subject = parts
            key = f"{stamp}\t{subject}"  # split/filtered repos rewrite hashes, so dedupe by time+subject
            if key in seen or email.lower() not in emails or subject.startswith(skip):
                continue
            seen.add(key)
            per_day[day] += 1
    return per_day


def compute_stats(per_day: Counter, start: dt.date, today: dt.date) -> dict:
    days = [start + dt.timedelta(d) for d in range((today - start).days + 1)]
    counts = [per_day.get(d.isoformat(), 0) for d in days]

    longest = run = 0
    longest_span = (None, None)
    run_start = None
    for d, c in zip(days, counts):
        if c:
            run_start = d if run == 0 else run_start
            run += 1
            if run > longest:
                longest, longest_span = run, (run_start, d)
        else:
            run = 0

    cur = 0
    i = len(days) - 1
    if counts[i] == 0:  # today not committed yet: streak still counts up to yesterday
        i -= 1
    cur_end = days[i]
    while i >= 0 and counts[i]:
        cur += 1
        i -= 1
    cur_span = (cur_end - dt.timedelta(cur - 1), cur_end) if cur else (None, None)

    total = sum(counts)
    active = sum(1 for c in counts if c)
    best_i = max(range(len(counts)), key=lambda k: counts[k])

    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    monthly = [sum(c for d, c in zip(days, counts) if (d.year, d.month) == ym) for ym in months]

    return {
        "days": days, "counts": counts, "total": total, "active": active,
        "span_days": len(days), "current": cur, "current_span": cur_span,
        "longest": longest, "longest_span": longest_span,
        "best": counts[best_i], "best_day": days[best_i],
        "avg": total / active if active else 0.0,
        "months": months, "monthly": monthly,
    }


# ---------------------------------------------------------------- svg parts

def window(width: int, height: int, title: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="12" fill="{BG}" stroke="{BORDER}"/>
<circle cx="22" cy="20" r="5.5" fill="#ff5f57"/><circle cx="40" cy="20" r="5.5" fill="#febc2e"/><circle cx="58" cy="20" r="5.5" fill="#28c840"/>
<text x="{width/2}" y="24" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{DIM}">{esc(title)}</text>
<line x1="0" y1="40" x2="{width}" y2="40" stroke="{BORDER}"/>
{body}
</svg>
"""


def prompt(x: float, y: float, handle: str, cmd: str, size: int = 15) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="600" xml:space="preserve">'
            f'<tspan fill="{TEAL}">{esc(handle)}@github</tspan><tspan fill="{DIM}"> ~ $ </tspan>'
            f'<tspan fill="{TEXT}">{esc(cmd)}</tspan></text>')


def level(c: int, cuts: list[int]) -> int:
    if c == 0:
        return 0
    for i, cut in enumerate(cuts, start=1):
        if c <= cut:
            return i
    return 4


def contributions_svg(st: dict, handle: str) -> str:
    days, counts = st["days"], st["counts"]
    nz = sorted(c for c in counts if c)
    cuts = [nz[int(len(nz) * q) - 1] if nz else 1 for q in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]

    cell, gap = 11, 3
    pitch = cell + gap
    first = days[0] - dt.timedelta((days[0].weekday() + 1) % 7)  # back to Sunday
    weeks = ((days[-1] - first).days // 7) + 1
    grid_w = weeks * pitch - gap
    left = (WIDTH - grid_w - 34) / 2 + 34
    top = 112

    parts = [prompt(28, 72, handle, "./contributions.sh")]
    last_month = None
    for w in range(weeks):
        d0 = first + dt.timedelta(w * 7)
        if d0.month != last_month and d0.day <= 7 and w < weeks - 2:
            parts.append(f'<text x="{left + w*pitch}" y="{top-10}" font-family="{MONO}" font-size="11" fill="{DIM}">{d0.strftime("%b")}</text>')
            last_month = d0.month
    for i, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(f'<text x="{left-34}" y="{top + i*pitch + 9}" font-family="{MONO}" font-size="10" fill="{DIM}">{lab}</text>')
    idx = {d: c for d, c in zip(days, counts)}
    for w in range(weeks):
        for k in range(7):
            d = first + dt.timedelta(w * 7 + k)
            if d not in idx:
                continue
            c = idx[d]
            parts.append(f'<rect x="{left + w*pitch}" y="{top + k*pitch}" width="{cell}" height="{cell}" rx="2" '
                         f'fill="{LEVELS[level(c, cuts)]}"><title>{d.isoformat()}: {c} commits</title></rect>')
    by = top + 7 * pitch + 22
    parts.append(f'<text x="{left-34}" y="{by}" font-family="{MONO}" font-size="12" fill="{TEXT}" font-weight="600">'
                 f'{st["total"]:,} commits in the last year<tspan fill="{DIM}" font-weight="400">  (all repos, incl. private)</tspan></text>')
    lx = left + grid_w - 5 * pitch - 70
    parts.append(f'<text x="{lx}" y="{by}" font-family="{MONO}" font-size="11" fill="{DIM}">Less</text>')
    for i, col in enumerate(LEVELS):
        parts.append(f'<rect x="{lx + 34 + i*pitch}" y="{by-10}" width="{cell}" height="{cell}" rx="2" fill="{col}"/>')
    parts.append(f'<text x="{lx + 34 + 5*pitch + 4}" y="{by}" font-family="{MONO}" font-size="11" fill="{DIM}">More</text>')
    return window(WIDTH, int(by + 26), f"{handle.upper()} / README.md", "\n".join(parts))


RAMP = " .:-=+*#%@"


def portrait_runs(path: str, crop: list[int], cols: int, cw: float, ch: float):
    img = Image.open(os.path.expanduser(path)).convert("RGBA").crop(tuple(crop))
    img = img.filter(ImageFilter.MinFilter(3))  # thicken the black line art so it survives downsampling
    w, h = img.size
    sx = w / cols
    rows = int(h / (sx * ch / cw))
    small = img.resize((cols, rows), Image.Resampling.BOX)
    lines = []
    for r in range(rows):
        runs = []  # (col, text, color)
        for c in range(cols):
            R, G, B, A = small.getpixel((c, r))
            if A < 90:
                ch_, col = " ", None
            else:
                lum = (0.2126 * R + 0.7152 * G + 0.0722 * B) / 255
                ch_ = RAMP[max(1, min(len(RAMP) - 1, int(lum * (len(RAMP) - 1) + 0.5)))]
                if lum < 0.3:  # black lines / hair / hoodie: keep black, just visible on a dark terminal
                    ch_, col = ".", "#3d444d"
                else:  # everything else keeps its original color (white skin, blue headphones)
                    q = lambda v: min(255, int(round(v / 16)) * 16)
                    col = f"#{q(R):02x}{q(G):02x}{q(B):02x}"
            if ch_ == " ":
                continue
            if runs and runs[-1][2] == col and runs[-1][0] + len(runs[-1][1]) == c:
                runs[-1] = (runs[-1][0], runs[-1][1] + ch_, col)
            else:
                runs.append((c, ch_, col))
        lines.append(runs)
    return lines


def fmt_span(span) -> str:
    a, b = span
    if not a:
        return "—"
    return f"{a.strftime('%b %-d')} – {b.strftime('%b %-d')}"


def whoami_svg(st: dict, cfg: dict) -> str:
    handle = cfg["handle"]
    parts = [prompt(28, 72, handle, "whoami")]

    # left: ascii portrait panel
    px, py, pw, ph = 24, 92, 330, 446
    parts.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>')
    cols, cw, ch = 72, 4.2, 7.2
    lines = portrait_runs(cfg["portrait"], cfg["portrait_crop"], cols, cw, ch)
    ox = px + (pw - cols * cw) / 2
    oy = py + 18 + (ph - 36 - len(lines) * ch) / 2
    for r, runs in enumerate(lines):
        if not runs:
            continue
        spans = "".join(f'<tspan x="{ox + c*cw:.1f}" fill="{col}">{esc(t)}</tspan>' for c, t, col in runs)
        parts.append(f'<text y="{oy + r*ch:.1f}" font-family="{MONO}" font-size="7" xml:space="preserve">{spans}</text>')
    parts.append(f'<text x="{px+12}" y="{py+ph-10}" font-family="{MONO}" font-size="10" fill="{DIM}">portrait.txt — rendered from my own character art</text>')

    # right: identity + stat tiles + monthly bars
    rx = px + pw + 22
    rw = WIDTH - rx - 24
    ident = cfg.get("whoami", [])
    for i, line in enumerate(ident):
        color, size, weight = (TEXT, 17, 700) if i == 0 else (DIM, 12.5, 400)
        parts.append(f'<text x="{rx}" y="{py + 18 + (0 if i == 0 else 8) + i*20}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{color}">{esc(line)}</text>')

    tiles = [
        ("current streak", f'{st["current"]}', "days", fmt_span(st["current_span"])),
        ("longest streak", f'{st["longest"]}', "days", fmt_span(st["longest_span"])),
        ("commits", f'{st["total"]:,}', "", "in the last year"),
        ("active days", f'{st["active"]}', f'/ {st["span_days"]}', "days with commits"),
        ("best day", f'{st["best"]}', "commits", st["best_day"].strftime("%b %-d, %Y")),
        ("avg / active day", f'{st["avg"]:.1f}', "", "commits"),
    ]
    ty = py + 18 + 8 + len(ident) * 20 + 4
    tw, th, tg = (rw - 12) / 2, 64, 10
    for i, (label, val, unit, sub) in enumerate(tiles):
        x = rx + (i % 2) * (tw + 12)
        y = ty + (i // 2) * (th + tg)
        parts.append(f'<rect x="{x}" y="{y}" width="{tw}" height="{th}" rx="6" fill="{PANEL}" stroke="{BORDER}"/>')
        parts.append(f'<text x="{x+12}" y="{y+18}" font-family="{MONO}" font-size="11" fill="{DIM}">$ {esc(label)}</text>')
        parts.append(f'<text x="{x+12}" y="{y+42}" font-family="{MONO}" font-size="22" font-weight="700" fill="{SKY}">{esc(val)}'
                     f'<tspan font-size="11" font-weight="400" fill="{DIM}"> {esc(unit)}</tspan></text>')
        parts.append(f'<text x="{x+12}" y="{y+57}" font-family="{MONO}" font-size="10" fill="{DIM}">{esc(sub)}</text>')

    by = ty + 3 * (th + tg)
    bh = py + ph - by
    parts.append(f'<rect x="{rx}" y="{by}" width="{rw}" height="{bh}" rx="6" fill="{PANEL}" stroke="{BORDER}"/>')
    parts.append(f'<text x="{rx+12}" y="{by+18}" font-family="{MONO}" font-size="11" fill="{DIM}">$ commits / month</text>')
    mx = max(st["monthly"]) or 1
    n = len(st["monthly"])
    area_x, area_w = rx + 14, rw - 28
    base = by + bh - 22
    top = by + 40
    bw = area_w / n * 0.62
    peak = st["monthly"].index(mx)
    for i, (v, (yy, mm)) in enumerate(zip(st["monthly"], st["months"])):
        hgt = (base - top) * v / mx
        x = area_x + i * area_w / n + (area_w / n - bw) / 2
        parts.append(f'<rect x="{x:.1f}" y="{base-hgt:.1f}" width="{bw:.1f}" height="{max(hgt,1):.1f}" rx="2" fill="{TEAL if i == peak else SKY}"><title>{yy}-{mm:02d}: {v}</title></rect>')
        if i == peak:
            parts.append(f'<text x="{x + bw/2:.1f}" y="{base-hgt-5:.1f}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="{TEXT}">{v}</text>')
        parts.append(f'<text x="{x + bw/2:.1f}" y="{base+14}" text-anchor="middle" font-family="{MONO}" font-size="9" fill="{DIM}">{dt.date(yy, mm, 1).strftime("%b")[0]}</text>')

    return window(WIDTH, py + ph + 20, f"{handle}@github: ~", "\n".join(parts))


def prompt_svg(handle: str, cmd: str) -> str:
    return window(WIDTH, 92, f"{handle}@github: ~", prompt(28, 72, handle, cmd))


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="YYYY-MM-DD (default: today, local time)")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    start = today - dt.timedelta(364)

    per_day = collect_commits(cfg, start)
    st = compute_stats(per_day, start, today)
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "contributions.svg").write_text(contributions_svg(st, cfg["handle"]))
    (ASSETS / "whoami.svg").write_text(whoami_svg(st, cfg))
    (ASSETS / "links.svg").write_text(prompt_svg(cfg["handle"], "./links.sh"))
    print(json.dumps({k: (str(v) if isinstance(v, (dt.date, tuple)) else v) for k, v in st.items()
                      if k not in ("days", "counts", "months")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
