"""Print the STRUCTURAL vocabulary of a captured profile page — class names, tag counts,
heading shapes. Deliberately prints no profile text, so the output is safe to share while
designing parser selectors.

Usage:
    python3 -m scripts.analyze_structure [fixture.html]
"""

import glob
import os
import re
import sys
from collections import Counter

from app.config import config


def main() -> int:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))
        if not cands:
            print("no .mwlite.html fixture found")
            return 2
        path = cands[-1]

    raw = open(path, encoding="utf-8").read()
    print(f"file: {os.path.basename(path)}  ({len(raw)} bytes)\n")

    classes: Counter[str] = Counter()
    for attr in re.findall(r'class="([^"]*)"', raw):
        for c in attr.split():
            classes[c] += 1

    # Structural names only: BEM-ish or hyphenated component names, skipping utility classes.
    util = re.compile(
        r"^(text|bg|p[xytblr]?|m[xytblr]?|w|h|flex|grid|border|items|justify|gap|min|max|"
        r"rounded|font|leading|top|left|right|bottom|absolute|relative|inline|self|overflow|"
        r"space|hidden|block|z|col|row|order|opacity|shadow|cursor|transition|ml|mr|mt|mb|pt|pb)"
        r"([-_].*)?$"
    )
    sem = {c: n for c, n in classes.items() if ("__" in c or "-" in c) and not util.match(c)}

    print("== semantic class names (top 60) ==")
    for c, n in sorted(sem.items(), key=lambda kv: -kv[1])[:60]:
        print(f"  {n:4d}  {c}")

    print("\n== element ids ==")
    ids = sorted(set(re.findall(r'id="([a-zA-Z0-9_\-]{3,50})"', raw)))
    print(" ", ids[:40])

    print("\n== tag counts ==")
    for tag in ["section", "article", "ul", "li", "h1", "h2", "h3", "h4", "a", "img", "time", "span", "p"]:
        pattern = "<" + tag + r"\b"
        count = len(re.findall(pattern, raw))
        print(f"  <{tag}>: {count}")

    print("\n== data-* attribute names ==")
    print(" ", sorted(set(re.findall(r'(data-[a-z0-9\-]+)=', raw)))[:40])

    print("\n== heading tag+class shapes (structure only) ==")
    for m in re.findall(r'<(h[1-4])[^>]*class="([^"]*)"', raw)[:25]:
        print(f"  <{m[0]}> class={m[1][:90]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
