"""Diagnostic: the DOM shape of the top card — tag, classes and ancestry for the first leaf
nodes after <h1>, so the headline/location can be selected by markup instead of guessed at by
text length.

Content is masked; only structure and lengths are printed.

Usage:
    python3 -m scripts.diag_topcard_dom <fixture.html>
"""

import glob
import os
import sys

from bs4 import BeautifulSoup

from app.config import config
from app.html_parser import _clean


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))[-1]

    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")
    print(f"fixture: {os.path.basename(path)}\n")

    h1 = soup.select_one("h1.heading-large, h1")
    print(f"<h1> classes={h1.get('class')}")
    print(f"h1 parent: <{h1.parent.name}> classes={h1.parent.get('class')}")
    print(f"h1 grandparent: <{h1.parent.parent.name}> classes={h1.parent.parent.get('class')}\n")

    print("== first 12 leaf nodes after <h1>: tag, own classes, parent classes, text length ==")
    seen: set[str] = set()
    n = 0
    for node in h1.find_all_next(["h2", "h3", "p", "span", "div", "a"], limit=120):
        if node.find(["h2", "h3", "p", "span", "div", "a"]):
            continue
        text = _clean(node.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        n += 1
        own = (node.get("class") or [])[:4]
        parent = (node.parent.get("class") or [])[:4]
        print(f"  [{n-1:2d}] <{node.name}> len={len(text):4d}")
        print(f"       own   : {own}")
        print(f"       parent: {parent}")
        if n >= 12:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
