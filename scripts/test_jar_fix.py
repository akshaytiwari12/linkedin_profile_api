"""Test the durable/volatile cookie split against the mwlite profile page.

Hypothesis: replaying stale __cf_bm / lidc causes the redirect loop. Seeding only durable
cookies and letting the session mint the volatile ones should restore a clean 200.

Usage:
    python3 -m scripts.test_jar_fix <public-identifier>
"""

import asyncio
import os
import sys

from app.config import config
from app.session_jar import durable_cookies, new_session

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
)


def headers() -> dict[str, str]:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
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

    seeded = durable_cookies()
    print(f"seeding {len(seeded)} durable cookies: {sorted(seeded)}")
    print("(volatile __cf_bm / lidc deliberately omitted)\n")

    async with new_session() as session:
        # Warm-up: hit the site root first so Cloudflare/LinkedIn issue fresh volatile cookies
        # into the jar before we ask for the profile — same order a browser would do it.
        try:
            warm = await session.get(
                "https://www.linkedin.com/",
                headers=headers(),
                impersonate="chrome131_android",
                timeout=45,
            )
            print(f"warm-up /: HTTP {warm.status_code}")
        except Exception as err:  # noqa: BLE001
            print(f"warm-up failed: {type(err).__name__}: {err}")

        got = {c.name for c in session.cookies.jar}
        print(f"jar after warm-up: {sorted(got)}")
        print(f"  minted volatile: {sorted(got & {'__cf_bm', 'lidc'})}\n")

        try:
            r = await session.get(
                f"https://www.linkedin.com/in/{identifier}/",
                headers=headers(),
                impersonate="chrome131_android",
                timeout=45,
            )
        except Exception as err:  # noqa: BLE001
            print(f"profile fetch FAILED: {type(err).__name__}: {err}")
            return 1

        html = r.text
        print(f"profile: HTTP {r.status_code} ({len(html)} bytes)")
        print(f"final url: {r.url}")

        if r.status_code == 200 and len(html) > 50000:
            os.makedirs(config.fixtures_dir, exist_ok=True)
            path = os.path.join(config.fixtures_dir, f"{identifier}.mwlite.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"saved: {path}")
            print("\nFIX CONFIRMED — stale volatile cookies were the cause.")
        else:
            print("\nStill not a full profile page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
