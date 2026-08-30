"""Probe the voyager GraphQL surface.

Replicates a queryId captured verbatim from browser traffic to validate that our headers,
cookies and fingerprint are accepted by /voyager/api/graphql, then tries profile-oriented
query names with the same hash pattern.

Usage:
    python3 -m scripts.probe_graphql
"""

import asyncio
import json
import os

from curl_cffi.requests import AsyncSession

from app.config import config
from app.linkedin_client import BASE_URL, build_headers

PACING_S = 15

# Captured verbatim from browser traffic — this one is known-good and acts as the control.
KNOWN_GOOD = "voyagerDashMySettings.8fdc6cac2e41f88f83e8d17dc78ac26c"


async def run(session: AsyncSession, label: str, url: str) -> dict | None:
    headers = build_headers()
    headers["accept"] = "application/vnd.linkedin.normalized+json+2.1"
    try:
        r = await session.get(
            url, headers=headers, impersonate=config.impersonate, allow_redirects=False, timeout=30
        )
    except Exception as err:  # noqa: BLE001
        print(f"  {label}: EXCEPTION {type(err).__name__}: {err}")
        return None

    print(f"  {label}: HTTP {r.status_code} ({len(r.content)} bytes)")
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        print("      not JSON")
        return None
    inc = data.get("included", []) if isinstance(data, dict) else []
    types = sorted({str(e.get("$type", "?")).split(".")[-1] for e in inc})
    print(f"      included={len(inc)} types={', '.join(types[:12]) or '(none)'}")
    return data


async def main() -> int:
    print("Control: replicate the captured queryId exactly\n")
    async with AsyncSession() as session:
        data = await run(
            session,
            "voyagerDashMySettings (captured)",
            f"{BASE_URL}/graphql?includeWebMetadata=true&variables=()&queryId={KNOWN_GOOD}",
        )
        if data is not None:
            os.makedirs(config.fixtures_dir, exist_ok=True)
            with open(os.path.join(config.fixtures_dir, "graphql_control.json"), "w") as fh:
                json.dump(data, fh, indent=2)
            print("\n  -> GraphQL surface ACCEPTS our requests.")
            print("     Remaining unknown is only the profile queryId hash.")
        else:
            print("\n  -> GraphQL rejected the captured query; headers/cookies still incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
