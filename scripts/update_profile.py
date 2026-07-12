#!/usr/bin/env python3
"""Sentinel Forge telemetry generator.

Queries the GitHub REST API for public, owned, non-fork repositories and
regenerates:

  * assets/telemetry.svg  - stat tiles + language distribution panel
  * README.md             - the ACTIVITY log block and LAST SYNC stamp
                            (only the regions between the HTML markers)

Design constraints:
  - Standard library only (runs on a bare GitHub Actions runner).
  - Never fabricates numbers: everything is computed from live API data.
  - Fails soft: on any API error the script logs and exits 0 without
    touching the committed files, so the profile keeps its last good state.
"""

from __future__ import annotations

import datetime
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

USER = "Jassim3nidad"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELEMETRY_PATH = os.path.join(ROOT, "assets", "telemetry.svg")
README_PATH = os.path.join(ROOT, "README.md")

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# Theme palette (keep in sync with assets/hero.svg)
FG = "#E6EDF3"
DIM = "#5A6873"
LABEL = "#8B98A5"
CYAN = "#56C8D8"
AMBER = "#E8A33D"
GREEN = "#56D364"
MAGENTA = "#C678DD"
TRACK = "#141C26"
BORDER = "#1E2C38"
PANEL = "#0E141B"

LANG_COLORS = {
    "TypeScript": CYAN,
    "JavaScript": AMBER,
    "Python": GREEN,
    "HTML": "#7FB3C8",
    "CSS": "#3DA8B8",
    "PLpgSQL": "#4A90A4",
    "PHP": MAGENTA,
}
DEFAULT_LANG_COLOR = LABEL

# Skip noisy automated commit subjects in the activity log.
NOISE = re.compile(r"^(merge\b|bump\b|chore\(deps|build\(deps|dependabot)", re.I)


def fetch(url: str):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{USER}-profile-telemetry")
    if TOKEN:
        req.add_header("Authorization", f"token {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect():
    repos = fetch(f"{API}/users/{USER}/repos?per_page=100&sort=pushed")
    repos = [r for r in repos if not r["fork"] and r["name"] != USER]
    user = fetch(f"{API}/users/{USER}")

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=90)

    langs: dict[str, int] = {}
    for r in repos:
        try:
            for lang, size in fetch(r["languages_url"]).items():
                langs[lang] = langs.get(lang, 0) + size
        except (urllib.error.URLError, urllib.error.HTTPError):
            continue  # one missing repo should not sink the whole panel

    stats = {
        "repos": len(repos),
        "deployed": sum(1 for r in repos if (r.get("homepage") or "").strip()),
        "active90": sum(
            1
            for r in repos
            if datetime.datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))
            >= cutoff
        ),
        "followers": user.get("followers", 0),
    }

    activity = []
    for r in repos[:8]:
        try:
            commits = fetch(f"{API}/repos/{USER}/{r['name']}/commits?per_page=3")
        except (urllib.error.URLError, urllib.error.HTTPError):
            continue
        subject = ""
        for c in commits:
            first_line = c["commit"]["message"].splitlines()[0].strip()
            if not NOISE.match(first_line):
                subject = first_line
                break
        if not subject:
            continue
        activity.append(
            {
                "repo": r["name"],
                "date": r["pushed_at"][:10],
                "subject": subject,
            }
        )
        if len(activity) == 5:
            break

    return stats, langs, activity, now


def build_svg(stats, langs, now) -> str:
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)
    shown = top[:6]
    other = sum(size for _, size in top[6:])
    if other:
        shown = shown[:5] + [("Other", other)]

    sync = now.strftime("%Y-%m-%d %H:%M UTC")

    tiles = [
        ("PUBLIC REPOS", stats["repos"], FG),
        ("DEPLOYED SYSTEMS", stats["deployed"], GREEN),
        ("ACTIVE / 90 DAYS", stats["active90"], AMBER),
        ("FOLLOWERS", stats["followers"], CYAN),
    ]

    parts = [
        '<svg viewBox="0 0 1000 400" xmlns="http://www.w3.org/2000/svg" '
        'role="img" aria-labelledby="telTitle telDesc">',
        f'<title id="telTitle">Development telemetry for {USER}</title>',
        f'<desc id="telDesc">Public repos: {stats["repos"]}. Deployed systems: '
        f'{stats["deployed"]}. Repos active in the last 90 days: {stats["active90"]}. '
        f'Followers: {stats["followers"]}. Top languages by bytes: '
        + ", ".join(f"{html.escape(n)} {100 * s / total:.1f} percent" for n, s in shown[:3])
        + f". Last sync {sync}.</desc>",
        "<style>.mono{font-family:ui-monospace,'Cascadia Mono','Segoe UI Mono',"
        "Menlo,Consolas,'Liberation Mono',monospace;}</style>",
        f'<rect x="1" y="1" width="998" height="398" rx="8" fill="#0B0F14" '
        f'stroke="{BORDER}" stroke-width="1.5"/>',
        f'<path d="M 14 26 V 14 H 26" fill="none" stroke="{CYAN}" stroke-width="1.5"/>',
        f'<path d="M 974 14 H 986 V 26" fill="none" stroke="{CYAN}" stroke-width="1.5"/>',
        f'<path d="M 986 374 V 386 H 974" fill="none" stroke="{CYAN}" stroke-width="1.5"/>',
        f'<path d="M 26 386 H 14 V 374" fill="none" stroke="{CYAN}" stroke-width="1.5"/>',
        f'<text x="48" y="38" class="mono" font-size="13" letter-spacing="2" '
        f'fill="{CYAN}">&#9698; DEVELOPMENT TELEMETRY</text>',
        f'<text x="952" y="38" text-anchor="end" class="mono" font-size="13" '
        f'letter-spacing="1" fill="{DIM}">LAST SYNC: {sync}</text>',
        f'<line x1="48" y1="52" x2="952" y2="52" stroke="#1C2A35" stroke-width="1"/>',
    ]

    x = 48
    for label, value, color in tiles:
        parts.append(
            f'<rect x="{x}" y="72" width="214" height="74" rx="4" '
            f'fill="{PANEL}" stroke="#1C2A35" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x + 16}" y="98" class="mono" font-size="12" '
            f'letter-spacing="2" fill="{DIM}">{label}</text>'
        )
        parts.append(
            f'<text x="{x + 16}" y="134" class="mono" font-size="30" '
            f'font-weight="700" fill="{color}">{value}</text>'
        )
        x += 230

    parts.append(
        f'<text x="48" y="186" class="mono" font-size="13" letter-spacing="2" '
        f'fill="{LABEL}">LANGUAGE DISTRIBUTION // SHARE OF PUBLIC CODE (BYTES)</text>'
    )

    y = 204
    for name, size in shown:
        pct = 100 * size / total
        width = max(2, round(560 * size / total))
        color = LANG_COLORS.get(name, DEFAULT_LANG_COLOR)
        label = html.escape(name.upper())
        parts.append(
            f'<text x="48" y="{y + 11}" class="mono" font-size="12.5" '
            f'fill="{LABEL}">{label}</text>'
        )
        parts.append(
            f'<rect x="190" y="{y}" width="560" height="12" rx="3" fill="{TRACK}"/>'
        )
        parts.append(
            f'<rect x="190" y="{y}" width="{width}" height="12" rx="3" '
            f'fill="{color}" opacity="0.85"/>'
        )
        parts.append(
            f'<text x="766" y="{y + 11}" class="mono" font-size="12.5" '
            f'fill="{FG}">{pct:.1f}%</text>'
        )
        y += 27

    parts.append(
        f'<text x="48" y="382" class="mono" font-size="12" letter-spacing="1" '
        f'fill="{DIM}">SOURCE: GITHUB REST API &#183; OWNED PUBLIC REPOS &#183; '
        f'NON-FORK &#183; NO THIRD-PARTY STAT SERVICES</text>'
    )
    parts.append(
        f'<text x="952" y="382" text-anchor="end" class="mono" font-size="12" '
        f'letter-spacing="2" fill="{DIM}">TELEMETRY.MOD</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_activity_block(activity) -> str:
    if not activity:
        return "```text\nNO RECENT TRANSMISSIONS LOGGED — check back after the next sync.\n```"
    lines = []
    for a in activity:
        repo = a["repo"][:20]
        subject = a["subject"].replace("`", "'").strip()
        if len(subject) > 46:
            subject = subject[:45] + "…"
        pad = "·" * max(2, 22 - len(repo))
        lines.append(f"{a['date']}  {repo} {pad} {subject}")
    return "```text\n" + "\n".join(lines) + "\n```"


def splice(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker), re.S
    )
    if not pattern.search(text):
        print(f"warning: markers {start_marker} not found in README", file=sys.stderr)
        return text
    return pattern.sub(start_marker + "\n" + replacement + "\n" + end_marker, text)


def main() -> int:
    try:
        stats, langs, activity, now = collect()
    except Exception as exc:  # noqa: BLE001 - fail soft by design
        print(f"telemetry refresh skipped, API unavailable: {exc}", file=sys.stderr)
        return 0

    svg = build_svg(stats, langs, now)
    with open(TELEMETRY_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)

    if os.path.exists(README_PATH):
        with open(README_PATH, encoding="utf-8") as fh:
            readme = fh.read()
        readme = splice(
            readme, "<!-- ACTIVITY:START -->", "<!-- ACTIVITY:END -->",
            build_activity_block(activity),
        )
        readme = splice(
            readme, "<!-- SYNC:START -->", "<!-- SYNC:END -->",
            now.strftime("`LAST TELEMETRY REFRESH: %Y-%m-%d %H:%M UTC`"),
        )
        with open(README_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(readme)

    print(
        f"telemetry refreshed: {stats['repos']} repos, "
        f"{len(langs)} languages, {len(activity)} activity entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
