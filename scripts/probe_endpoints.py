"""Probe candidate voyager endpoints to find which profile surface is still live.

Spaced conservatively (see PACING_S) because every request is charged against a session that
costs a manual browser re-login to replace. Uses the impersonating client, never raw curl.

Usage:
    python3 -m scripts.probe_endpoints <public-identifier>
"""

import asyncio
import json
import os
import sys

from curl_cffi.requests import AsyncSession

from app.config import config
from app.linkedin_client import BASE_URL, build_headers

PACING_S = 20

CANDIDATES: list[tuple[str, str]] = [
    # Control: known-good, confirms the session is still alive between probes.
    ("control: /me", "/me"),
    # The "dash" (Data Access Service Hub) surface that superseded the old identity endpoints.
    (
        "dash profiles by memberIdentity",
        "/identity/dash/profiles?q=memberIdentity&memberIdentity={id}",
    ),
    # Same, asking for the full decoration (entities included). Decoration ids are versioned and
    # may 400 even when the base endpoint works.
    (
        "dash profiles + FullProfileWithEntities",
        "/identity/dash/profiles?q=memberIdentity&memberIdentity={id}"
        "&decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-101",
    ),
    # Legacy-style top card, still referenced by some surfaces.
    ("legacy profile root", "/identity/profiles/{id}"),
]


async def probe(session: AsyncSession, label: str, path: str, identifier: str) -> dict | None:
    url = f"{BASE_URL}{path.replace('{id}', identifier)}"
    try:
        r = await session.get(
            url,
            headers=build_headers(),
            impersonate=config.impersonate,
            allow_redirects=False,
            timeout=30,
        )
    except Exception as err:  # noqa: BLE001
        print(f"  {label}: EXCEPTION {type(err).__name__}: {err}")
        return None

    print(f"  {label}: HTTP {r.status_code}  ({len(r.content)} bytes)")
    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            print("      (200 but body is not JSON)")
            return None
        included = data.get("included", []) if isinstance(data, dict) else []
        types = sorted({str(e.get("$type", "?")).split(".")[-1] for e in included})
        print(f"      included={len(included)} types={', '.join(types[:12]) or '(none)'}")
        return data
    return None


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    identifier = sys.argv[1]

    print(f"Probing candidate endpoints for '{identifier}' ({PACING_S}s apart)\n")
    winners: dict[str, dict] = {}

    async with AsyncSession() as session:
        for i, (label, path) in enumerate(CANDIDATES):
            data = await probe(session, label, path, identifier)
            if data:
                winners[label] = data
            if i < len(CANDIDATES) - 1:
                await asyncio.sleep(PACING_S)

    if winners:
        os.makedirs(config.fixtures_dir, exist_ok=True)
        for label, data in winners.items():
            slug = label.replace(" ", "_").replace(":", "").replace("/", "")
            path = os.path.join(config.fixtures_dir, f"{identifier}.{slug}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            print(f"\nsaved: {path}")
    else:
        print("\nNo endpoint returned 200.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
