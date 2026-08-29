"""Load the mwlite profile page and extract the GraphQL queryIds it references.

Discovering queryIds at runtime is what keeps a client working across LinkedIn deploys — the
hashes rotate, so hardcoding one is as brittle as hardcoding a CSS selector.

Usage:
    python3 -m scripts.mine_query_ids <public-identifier>
"""

import asyncio
import os
import re
import sys

from curl_cffi.requests import AsyncSession

from app.config import config

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
)

HEX32 = re.compile(r"\b[0-9a-f]{32}\b")


def page_headers() -> dict[str, str]:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "cookie": config.cookie_jar
        or f'li_at={config.li_at}; JSESSIONID="{config.jsessionid}"',
        "user-agent": MOBILE_UA,
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "upgrade-insecure-requests": "1",
    }


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    identifier = sys.argv[1]

    async with AsyncSession() as session:
        r = await session.get(
            f"https://www.linkedin.com/in/{identifier}/",
            headers=page_headers(),
            impersonate="chrome131_android",
            allow_redirects=True,
            timeout=45,
        )
        html = r.text
        print(f"page: HTTP {r.status_code} ({len(html)} bytes) final={r.url}")

        os.makedirs(config.fixtures_dir, exist_ok=True)
        with open(os.path.join(config.fixtures_dir, f"{identifier}.mwlite.html"), "w") as fh:
            fh.write(html)

        # queryIds appear near their query names in the bundles; capture surrounding context so
        # we can tell a profile query from an unrelated one.
        hashes = sorted(set(HEX32.findall(html)))
        print(f"\n32-hex candidates in page: {len(hashes)}")
        for h in hashes[:20]:
            idx = html.find(h)
            ctx = html[max(0, idx - 90) : idx + 40].replace("\n", " ")
            print(f"  {h}\n     ...{ctx}...")

        bundles = sorted(set(re.findall(r'https://static\.licdn\.com/[^\s"\']+\.js', html)))
        print(f"\nJS bundles referenced: {len(bundles)}")
        for b in bundles[:10]:
            print(f"  {b}")

        # Fetch the bundles most likely to hold profile queries and mine those too.
        interesting = [b for b in bundles if re.search(r"profile|mwlite", b, re.I)][:3]
        for b in interesting:
            try:
                rb = await session.get(b, impersonate="chrome131_android", timeout=45)
            except Exception as err:  # noqa: BLE001
                print(f"\nbundle {b}: EXCEPTION {err}")
                continue
            js = rb.text
            print(f"\nbundle {b.split('/')[-1]}: HTTP {rb.status_code} ({len(js)} bytes)")
            pairs = re.findall(r'["\']([A-Za-z][A-Za-z0-9_]{4,60})["\']\s*:\s*["\']([0-9a-f]{32})["\']', js)
            named = [(n, h) for n, h in pairs]
            print(f"  name->hash pairs: {len(named)}")
            for n, h in named[:25]:
                print(f"    {n} = {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
