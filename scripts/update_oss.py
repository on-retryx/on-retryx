#!/usr/bin/env python3
"""Refresh the open-source contribution card and PR table on the profile README.

Reads public data from the GitHub API (stdlib only), then writes:
  - assets/oss-stats.svg              the stats card
  - README.md between OSS markers     one row per merged or open PR

Only PRs to repositories owned by someone else are counted. PRs closed without
merging are left out of both the card and the table.

The card uses the RetryX Pop Noir kit; brand fonts from assets/fonts are
embedded so the SVG looks the same in every browser.
"""
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "on-retryx")
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CARD = ROOT / "assets" / "oss-stats.svg"
FONTS = ROOT / "assets" / "fonts"
START, END = "<!-- OSS:START -->", "<!-- OSS:END -->"

# RetryX Pop Noir (dark)
BG, SURFACE, LINE, INK, MUTED = "#0B0B0D", "#17171B", "#2A2A31", "#F5F5F0", "#A1A1AA"
ACCENT, DONE, YELLOW = "#FF3D7F", "#39FF88", "#FFD23F"


def api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-oss-stats",
        **({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def collect():
    q = urllib.parse.quote(f"author:{USER} type:pr -user:{USER}")
    items = api(f"/search/issues?q={q}&per_page=100&sort=created&order=desc")["items"]
    prs, stars = [], {}
    for it in items:
        repo = it["repository_url"].split("/repos/", 1)[1]
        pr = api(f"/repos/{repo}/pulls/{it['number']}")
        if pr["merged_at"]:
            state = "merged"
        elif pr["state"] == "open":
            state = "draft" if pr.get("draft") else "open"
        else:
            continue  # closed without merge
        if repo not in stars:
            stars[repo] = api(f"/repos/{repo}")["stargazers_count"]
        prs.append({
            "repo": repo, "number": pr["number"], "title": pr["title"], "url": pr["html_url"],
            "state": state, "add": pr["additions"], "del": pr["deletions"],
            "files": pr["changed_files"], "talk": pr["comments"] + pr["review_comments"],
            "date": (pr["merged_at"] or pr["created_at"])[:10],
        })
    order = {"merged": 0, "open": 1, "draft": 2}
    prs.sort(key=lambda p: p["date"], reverse=True)  # newest first...
    prs.sort(key=lambda p: order[p["state"]])  # ...within merged, then open, then draft
    return prs, stars


def short(n):
    return f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else str(n)


def font_faces():
    faces = [("Archivo Black", 400, "archivo-black"), ("Space Mono", 400, "spacemono-400"), ("Space Mono", 700, "spacemono-700")]
    out = []
    for family, weight, name in faces:
        data = base64.b64encode((FONTS / f"{name}.woff2").read_bytes()).decode()
        out.append(f'@font-face{{font-family:"{family}";font-weight:{weight};src:url(data:font/woff2;base64,{data}) format("woff2")}}')
    return "".join(out)


def card(prs, stars):
    merged = sum(p["state"] == "merged" for p in prs)
    review = sum(p["state"] != "merged" for p in prs)
    add = sum(p["add"] for p in prs)
    dele = sum(p["del"] for p in prs)
    tiles = [
        (str(merged), "MERGED PRs", DONE),
        (str(review), "IN REVIEW", YELLOW),
        (f"+{short(add)}", f"LINES (−{short(dele)})", INK),
    ]
    w, h, pad, gap = 1000, 190, 36, 18
    tw = (w - 2 * pad - (len(tiles) - 1) * gap) / len(tiles)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Open source: {merged} merged PRs, {review} in review, +{add} lines changed">',
        f'<defs><style>{font_faces()}'
        '.m{font-family:"Space Mono",ui-monospace,Menlo,Consolas,monospace;font-weight:400}'
        '.b{font-family:"Space Mono",ui-monospace,Menlo,Consolas,monospace;font-weight:700}'
        '.s{font-family:"Archivo Black",system-ui,sans-serif}</style>'
        f'<pattern id="dots" width="25" height="25" patternUnits="userSpaceOnUse"><circle cx="12.5" cy="12.5" r="1.6" fill="{ACCENT}" fill-opacity=".2"/></pattern></defs>',
        f'<rect width="{w}" height="{h}" rx="20" fill="{BG}"/>',
        f'<rect width="{w}" height="{h}" rx="20" fill="url(#dots)"/>',
        f'<text x="{pad}" y="46" class="m" font-size="15" fill="{MUTED}"><tspan fill="{ACCENT}">$</tspan> git log --author={USER} --upstream   # open source, live from the GitHub API</text>',
    ]
    for i, (big, label, color) in enumerate(tiles):
        x = pad + i * (tw + gap)
        out += [
            f'<rect x="{x:.1f}" y="66" width="{tw:.1f}" height="96" rx="12" fill="{SURFACE}" stroke="{LINE}" stroke-width="1.5"/>',
            f'<rect x="{x + 18:.1f}" y="88" width="4" height="52" rx="2" fill="{color}"/>',
            f'<text x="{x + tw / 2:.1f}" y="121" text-anchor="middle" class="s" font-size="40" fill="{color}">{escape(big)}</text>',
            f'<text x="{x + tw / 2:.1f}" y="147" text-anchor="middle" class="b" font-size="13" letter-spacing="1.5" fill="{MUTED}">{escape(label)}</text>',
        ]
    out.append("</svg>")
    return "\n".join(out) + "\n"


def table(prs, stars):
    badge = {
        "merged": "![done: merged](https://img.shields.io/badge/%E2%9C%93_merged-39FF88?style=flat-square)",
        "open": "![in review](https://img.shields.io/badge/in_review-FFD23F?style=flat-square)",
        "draft": "![draft](https://img.shields.io/badge/draft-3F3F46?style=flat-square)",
    }
    rows = ["| | project | pull request | status | diff |", "|:-:|---|---|:-:|--:|"]
    for repo in dict.fromkeys(p["repo"] for p in prs):  # repos in table order
        owner = repo.split("/")[0]
        for i, p in enumerate(x for x in prs if x["repo"] == repo):
            # escape so titles like "<script>" show as text, not HTML
            title = escape(p["title"], quote=False).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
            head = (f'<img src="https://github.com/{owner}.png?size=40" width="20" alt="">',
                    f'[{repo}](https://github.com/{repo}) <sub>★ {short(stars[repo])}</sub>') if i == 0 else ("", "")
            rows.append(
                f'| {head[0]} | {head[1]} '
                f'| [{title}]({p["url"]}) <sub>#{p["number"]}</sub> '
                f'| {badge[p["state"]]} | `+{p["add"]} −{p["del"]}` |'
            )
    if len(prs) == 0:
        rows.append("| | nothing yet | | | |")
    return "\n".join(rows)


def main():
    prs, stars = collect()
    CARD.write_text(card(prs, stars), encoding="utf-8")
    text = README.read_text(encoding="utf-8")
    block = f"{START}\n{table(prs, stars)}\n{END}"
    new, n = re.subn(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    if n != 1:
        sys.exit("OSS markers not found in README.md")
    README.write_text(new, encoding="utf-8")
    print(f"{len(prs)} PRs, {sum(stars.values())} stars across {len(stars)} repos")


if __name__ == "__main__":
    main()
