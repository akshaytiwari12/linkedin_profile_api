"""Run the current parser against a captured fixture. No LinkedIn request, no session risk.

This is the inner development loop: iterate on profile_parser.py and re-run this until the
output is right, spending zero LinkedIn requests.

Usage:
    python3 -m scripts.replay_fixture [fixture-path]      # defaults to the only/first fixture
"""

import glob
import json
import os
import sys

from app.config import config
from app.profile_parser import parse_profile_view


def main() -> int:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        candidates = sorted(glob.glob(os.path.join(config.fixtures_dir, "*.profileView.json")))
        if not candidates:
            print(
                f"No fixtures in {config.fixtures_dir}/. "
                "Capture one first: python3 -m scripts.capture_fixture <profile-url>"
            )
            return 2
        path = candidates[0]

    identifier = os.path.basename(path).replace(".profileView.json", "")
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)

    profile = parse_profile_view(raw, identifier, f"https://www.linkedin.com/in/{identifier}/")
    print(json.dumps(profile, indent=2))

    # Quick signal on which sections actually populated — the fields most likely to silently
    # come back empty if LinkedIn moved them to a different entity type or endpoint.
    print("\n--- coverage ---", file=sys.stderr)
    for field in ("headline", "location", "about"):
        print(f"  {field:15s}: {'OK' if profile.get(field) else 'EMPTY'}", file=sys.stderr)
    for field in ("experience", "education", "skills", "certifications", "languages", "profileImages"):
        print(f"  {field:15s}: {len(profile.get(field) or [])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
