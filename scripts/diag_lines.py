"""Diagnostic: what do the text lines inside an entity lockup look like?

Letters are masked (A/a) while digits, punctuation and spacing are preserved, so the output
reveals the FORMAT of each line — enough to write date/location parsing — without exposing the
profile's actual content.

Usage:
    python3 -m scripts.diag_lines [fixture.html]
"""

import glob
import os
import re
import sys

from bs4 import BeautifulSoup

from app.config import config
from app.html_parser import _lockup_lines


def mask(text: str) -> str:
    out = []
    for ch in text:
        if ch.isupper():
            out.append("A")
        elif ch.islower():
            out.append("a")
        else:
            out.append(ch)  # digits, punctuation, spaces kept verbatim
    return "".join(out)


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

    for idx in (0, 2, 14):
        if idx >= len(lockups):
            continue
        lk = lockups[idx]
        print(f"=== lockup[{idx}] (masked) ===")
        print(f"  full text: {mask(re.sub(r'[ ]+', ' ', lk.get_text(' ', strip=True)))[:300]}")
        print("  leaf lines:")
        for line in _lockup_lines(lk):
            print(f"    {mask(line)[:160]}")
        print()

    print("=== certification/language item sample (masked) ===")
    for h in soup.find_all(["h2", "h3"]):
        label = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).lower()
        if label in ("certifications", "languages"):
            nxt = h.find_next("li")
            if nxt:
                print(f"  under {label!r}: {mask(nxt.get_text(' ', strip=True))[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
