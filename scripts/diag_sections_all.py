"""Diagnostic: which profile sections does the fetched page actually contain?

Answers "is this field missing because the parser failed, or because LinkedIn never sent it?".
Prints section headings and element counts only — no profile content.

Usage:
    python3 -m scripts.diag_sections_all [fixture.html]
"""

import glob
import os
import re
import sys

from bs4 import BeautifulSoup

from app.config import config
from app.html_parser import _clean

SECTIONISH = re.compile(
    r"^(experience|education|skills|languages|licen|certif|volunteer|honors|awards|"
    r"projects?|courses?|publications?|recommendations?|interests?|organizations?)",
    re.I,
)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = args or sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))
    if not paths:
        print("no fixtures found")
        return 2

    for path in paths:
        soup = BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")

        headings = []
        for h in soup.find_all(["h2", "h3"]):
            text = _clean(h.get_text(" ", strip=True)) or ""
            if SECTIONISH.match(text):
                headings.append(f"<{h.name}>{text}")

        print(f"{os.path.basename(path)}")
        print(f"   sections present : {headings}")
        print(
            f"   counts           : lockups={len(soup.select('.profile-entity-lockup'))}"
            f" skill-item={len(soup.select('.skill-item'))}"
            f" sub-list-item={len(soup.select('.sub-list-item'))}"
        )
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
