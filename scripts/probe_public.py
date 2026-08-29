"""Fetch the PUBLIC profile page with no cookies at all — zero session risk.

Two things we want from it:
  1. Whether the page carries a JSON-LD block (the no-auth fallback data source).
  2. GraphQL queryIds / JS bundle URLs, which is what a self-healing GraphQL client would
     discover at runtime rather than hardcode.

Usage:
    python3 -m scripts.probe_public <public-identifier>
"""

import asyncio
import os
import re
import sys

from curl_cffi.requests import AsyncSession

from app.config import config


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    identifier = sys.argv[1]
    url = f"https://www.linkedin.com/in/{identifier}"

    async with AsyncSession() as session:
        try:
            # No cookie header at all. curl_cffi supplies a full browser header set to match
            # the impersonated fingerprint, which is what the HTML flow expects.
            r = await session.get(
                url, impersonate=config.impersonate, allow_redirects=True, timeout=40
            )
        except Exception as err:  # noqa: BLE001
            print(f"EXCEPTION {type(err).__name__}: {err}")
            return 1

    html = r.text
    print(f"HTTP {r.status_code}  ({len(html)} bytes)")
    print(f"final url: {r.url}")

    ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    print(f"\nJSON-LD blocks: {len(ld)}")
    if ld:
        preview = ld[0][:400].replace("\n", " ")
        print(f"  first block preview: {preview}")

    qids = sorted(set(re.findall(r"voyager[A-Za-z]+\.[0-9a-f]{16,}", html)))
    print(f"\nqueryIds in HTML: {len(qids)}")
    for q in qids[:15]:
        print(f"  {q}")

    bundles = sorted(set(re.findall(r"https://static\.licdn\.com/[^\s\"']+\.js", html)))
    print(f"\nJS bundles: {len(bundles)}")
    for b in bundles[:5]:
        print(f"  {b}")

    markers = {
        "authwall": "authwall" in html.lower(),
        "rsc-action": "rsc-action" in html,
        "__NEXT_DATA__": "__NEXT_DATA__" in html,
        "code blocks (<!--{)": html.count("<!--{"),
    }
    print("\nmarkers:")
    for k, v in markers.items():
        print(f"  {k}: {v}")

    os.makedirs(config.fixtures_dir, exist_ok=True)
    path = os.path.join(config.fixtures_dir, f"{identifier}.public.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\nsaved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
