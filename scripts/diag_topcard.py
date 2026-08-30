"""Diagnostic: top-card line candidates and which sections exist on a fixture.

Letters are masked, so line FORMAT and length are visible without the content.

Usage:
    python3 -m scripts.diag_topcard <fixture.html>
"""

import glob
import os
import re
import sys

from bs4 import BeautifulSoup

from app.config import config
from app.html_parser import _clean

SECTIONS = re.compile(r"^(experience|education|skills|languages|licen[sc]es|certification)", re.I)


def mask(text: str) -> str:
    return "".join("A" if c.isupper() else "a" if c.islower() else c for c in text)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        path = args[0]
    else:
        cands = sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))
        path = cands[-1]

    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")
    print(f"fixture: {os.path.basename(path)}\n")

    name_el = soup.select_one("h1.heading-large, h1")
    print("== first 8 leaf lines after <h1> (masked) ==")
    seen: list[str] = []
    for sib in name_el.find_all_next(["h2", "p", "span", "div"], limit=60):
        if sib.find(["h2", "p", "span", "div"]):
            continue
        text = _clean(sib.get_text(" ", strip=True))
        if text and text not in seen:
            seen.append(text)
            has_comma = "," in text
            print(f"  [{len(seen)-1}] len={len(text):3d} comma={has_comma!s:5s} {mask(text)[:90]}")
        if len(seen) >= 8:
            break

    print("\n== section headings present ==")
    for h in soup.find_all(["h2", "h3"]):
        t = _clean(h.get_text(" ", strip=True)) or ""
        if SECTIONS.match(t):
            print(f"  <{h.name}> {t!r}")

    print("\n== counts ==")
    print(f"  .profile-entity-lockup : {len(soup.select('.profile-entity-lockup'))}")
    print(f"  .skill-item            : {len(soup.select('.skill-item'))}")
    print(f"  .sub-list-item         : {len(soup.select('.sub-list-item'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
