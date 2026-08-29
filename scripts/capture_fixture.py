"""Spend exactly ONE LinkedIn request to capture a real profileView payload to disk.

Every session costs a manual browser re-login to replace, so the workflow is: capture once,
then develop the parser offline against the fixture (scripts/replay_fixture.py) instead of
re-fetching on every iteration.

Usage:
    python3 -m scripts.capture_fixture <profile-url-or-identifier>
"""

import asyncio
import json
import os
import sys

from app.config import config
from app.linkedin_client import fetch_profile_view
from app.profile_url import extract_public_identifier


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    target = sys.argv[1]
    identifier = extract_public_identifier(target) if "/" in target else target

    print(f"Fetching profileView for '{identifier}' (impersonate={config.impersonate}) ...")
    try:
        raw = await fetch_profile_view(identifier)
    except Exception as err:  # noqa: BLE001 - surfaced verbatim; this is a diagnostic script
        print(f"FAILED: {type(err).__name__}: {err}")
        return 1

    os.makedirs(config.fixtures_dir, exist_ok=True)
    path = os.path.join(config.fixtures_dir, f"{identifier}.profileView.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle, indent=2)

    included = raw.get("included", []) if isinstance(raw, dict) else []
    types = sorted({str(e.get("$type", "?")).split(".")[-1] for e in included})

    print(f"OK  saved: {path}")
    print(f"    included entities: {len(included)}")
    print(f"    entity types: {', '.join(types) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
