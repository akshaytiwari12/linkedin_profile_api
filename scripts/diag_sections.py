"""Diagnostic: how are entity lockups attached to their sections?

Prints tag names, class lists, and section heading labels ("Experience", "Education", ...) plus
line COUNTS — never the profile text itself — so the output is safe to share.

Usage:
    python3 -m scripts.diag_sections [fixture.html]
"""

import glob
import os
import re
import sys

from bs4 import BeautifulSoup

from app.config import config

GENERIC = re.compile(r"^(experience|education|skills|languages|licen[sc]es|certification)", re.I)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        path = args[0]
    else:
        cands = sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))
        if not cands:
            print("no fixture found")
            return 2
        path = cands[-1]

    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")

    lockups = soup.select(".profile-entity-lockup")
    print(f"profile-entity-lockup count: {len(lockups)}\n")

    for i, lk in enumerate(lockups):
        prev = lk.find_previous(["h2", "h3"])
        label = re.sub(r"\s+", " ", prev.get_text(" ", strip=True))[:40] if prev else "(none)"
        # Only print the label if it looks like a generic section name, never free text.
        safe_label = label if GENERIC.match(label) else f"<non-section:{len(label)}ch>"
        heading = lk.select_one(".list-item-heading")
        print(
            f"  [{i:2d}] tag=<{lk.name}> classes={(lk.get('class') or [])[:3]} "
            f"prevHeading={safe_label!r} hasListItemHeading={heading is not None}"
        )

    print("\n== all h2/h3 that look like section labels ==")
    for h in soup.find_all(["h2", "h3"]):
        t = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
        if GENERIC.match(t):
            print(f"  <{h.name}> {t[:50]!r} classes={(h.get('class') or [])[:4]}")

    print("\n== #about-profile structure ==")
    about = soup.select_one("#about-profile")
    if not about:
        print("  (#about-profile not found)")
    else:
        print(f"  tag=<{about.name}> classes={about.get('class')}")
        for child in about.find_all(True, recursive=True, limit=15):
            text_len = len(re.sub(r"\s+", " ", child.get_text(" ", strip=True)))
            print(f"    <{child.name}> classes={(child.get('class') or [])[:3]} textLen={text_len}")

    print("\n== skill-item sample structure ==")
    for item in soup.select(".skill-item")[:2]:
        print(f"  tag=<{item.name}> classes={(item.get('class') or [])[:3]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
