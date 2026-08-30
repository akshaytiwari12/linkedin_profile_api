"""Run the HTML parser against a captured fixture and report field coverage.

Prints counts and lengths rather than profile text, so the output is safe to share while
iterating on selectors. Pass --show to print the full JSON locally when you need to eyeball it.

Usage:
    python3 -m scripts.replay_html [fixture.html] [--show]
"""

import glob
import json
import os
import sys

from app.config import config
from app.html_parser import parse_profile_html


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show = "--show" in sys.argv

    if args:
        path = args[0]
    else:
        cands = sorted(glob.glob(os.path.join(config.fixtures_dir, "*.mwlite.html")))
        if not cands:
            print("no .mwlite.html fixture found")
            return 2
        path = cands[-1]

    identifier = os.path.basename(path).replace(".mwlite.html", "")
    html = open(path, encoding="utf-8").read()
    profile = parse_profile_html(html, identifier, f"https://www.linkedin.com/in/{identifier}/")

    print(f"fixture: {os.path.basename(path)}\n")
    print("== scalar fields ==")
    for field in ("fullName", "firstName", "lastName", "headline", "location", "about"):
        value = profile.get(field)
        status = f"OK  ({len(value)} chars)" if value else "EMPTY"
        print(f"  {field:12s}: {status}")

    print("\n== list fields ==")
    for field in ("experience", "education", "skills", "certifications", "languages", "profileImages"):
        print(f"  {field:14s}: {len(profile.get(field) or [])}")

    print("\n== per-entry completeness ==")
    for i, exp in enumerate(profile.get("experience") or []):
        filled = [k for k, v in exp.items() if v not in (None, False, [], {})]
        print(f"  experience[{i}]: {sorted(filled)}")
    for i, edu in enumerate(profile.get("education") or []):
        filled = [k for k, v in edu.items() if v not in (None, False, [], {})]
        print(f"  education[{i}] : {sorted(filled)}")
    for i, cert in enumerate(profile.get("certifications") or []):
        filled = [k for k, v in cert.items() if v not in (None, False, [], {})]
        print(f"  cert[{i}]      : {sorted(filled)}")

    if show:
        print("\n== full JSON ==")
        print(json.dumps(profile, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
