"""Second probe round: URN-addressed endpoints, plus mining the profile page for queryIds.

Usage:
    python3 -m scripts.probe_urn <urn> <public-identifier>
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from app.config import config
from app.linkedin_client import BASE_URL, build_headers

PACING_S = 20


async def api_probe(session: AsyncSession, label: str, path: str) -> dict | None:
    try:
        r = await session.get(
            f"{BASE_URL}{path}",
            headers=build_headers(),
            impersonate=config.impersonate,
            allow_redirects=False,
            timeout=30,
        )
    except Exception as err:  # noqa: BLE001
        print(f"  {label}: EXCEPTION {type(err).__name__}: {err}")
        return None

    print(f"  {label}: HTTP {r.status_code} ({len(r.content)} bytes)")
    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            print("      (not JSON)")
            return None
        inc = data.get("included", []) if isinstance(data, dict) else []
        types = sorted({str(e.get("$type", "?")).split(".")[-1] for e in inc})
        print(f"      included={len(inc)} types={', '.join(types[:15]) or '(none)'}")
        return data
    return None


async def mine_page_for_query_ids(session: AsyncSession, identifier: str) -> None:
    """Fetch the profile page HTML and extract any GraphQL queryIds it references.

    queryIds are build-hash identifiers baked into LinkedIn's bundles; discovering them at
    runtime (rather than hardcoding) is what would make a GraphQL client self-healing across
    LinkedIn deploys.
    """
    url = f"https://www.linkedin.com/in/{identifier}/"
    headers = {k: v for k, v in build_headers().items() if k in ("cookie", "referer")}
    headers["accept"] = "text/html,application/xhtml+xml"

    try:
        r = await session.get(
            url, headers=headers, impersonate=config.impersonate, allow_redirects=True, timeout=40
        )
    except Exception as err:  # noqa: BLE001
        print(f"  profile page: EXCEPTION {type(err).__name__}: {err}")
        return

    html = r.text
    print(f"  profile page: HTTP {r.status_code} ({len(html)} bytes) final={r.url}")

    query_ids = sorted(set(re.findall(r'voyager[A-Za-z]+\.[0-9a-f]{16,}', html)))
    print(f"      queryIds found in HTML: {len(query_ids)}")
    for q in query_ids[:20]:
        print(f"        {q}")

    bundles = sorted(set(re.findall(r'https://static\.licdn\.com/[^\s"\']+\.js', html)))
    print(f"      JS bundles referenced: {len(bundles)}")

    has_ld = "application/ld+json" in html
    print(f"      JSON-LD block present: {has_ld}")

    os.makedirs(config.fixtures_dir, exist_ok=True)
    path = os.path.join(config.fixtures_dir, f"{identifier}.page.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"      saved: {path}")


async def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    urn, identifier = sys.argv[1], sys.argv[2]
    enc = quote(urn, safe="")

    print(f"Round 2 probes for {urn}\n")
    winners: dict[str, dict] = {}

    candidates = [
        ("dash profile by urn", f"/identity/dash/profiles/{enc}"),
        ("dash profiles q=memberIdentity(urn)", f"/identity/dash/profiles?q=memberIdentity&memberIdentity={enc}"),
    ]

    async with AsyncSession() as session:
        for i, (label, path) in enumerate(candidates):
            data = await api_probe(session, label, path)
            if data:
                winners[label] = data
            await asyncio.sleep(PACING_S)

        await mine_page_for_query_ids(session, identifier)

    for label, data in winners.items():
        slug = label.replace(" ", "_").replace("=", "").replace("(", "").replace(")", "")
        p = os.path.join(config.fixtures_dir, f"{identifier}.{slug}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        print(f"\nsaved: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
