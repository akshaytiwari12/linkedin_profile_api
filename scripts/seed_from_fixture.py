"""Load a captured fixture into the raw-payload store so the API can be exercised end to end
without making any LinkedIn request.

This is the same path a live fetch takes (store raw -> parse -> cache), just with the network
step replaced by a file read.

Usage:
    python3 -m scripts.seed_from_fixture [fixture.html]
"""

import glob
import os
import sys

from app import stores
from app.config import config
from app.html_parser import PARSER_VERSION, parse_profile_html


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

    identifier = os.path.basename(path).replace(".mwlite.html", "")
    html = open(path, encoding="utf-8").read()
    profile_url = f"https://www.linkedin.com/in/{identifier}/"

    record = stores.save_raw_payload(identifier, html)
    profile = parse_profile_html(html, identifier, profile_url)
    stores.set_cached(identifier, profile, PARSER_VERSION, record["id"])

    print(f"seeded {identifier}")
    print(f"  raw payload id : {record['id']}")
    print(f"  experience     : {len(profile['experience'])}")
    print(f"  education      : {len(profile['education'])}")
    print(f"  skills         : {len(profile['skills'])}")
    print(f"\ntry: curl 'http://localhost:8000/api/profile?url={profile_url}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
