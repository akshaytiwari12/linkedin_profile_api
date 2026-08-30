"""Can this run unattended, or does it need a fresh cookie paste every 30 minutes?

The configured LI_COOKIE_JAR contains __cf_bm, which expires after 30 minutes of inactivity. If
the service can only work by replaying that value, a deployed instance is useless — it would
serve for half an hour and then redirect-loop.

This seeds a session with the DURABLE cookies only, lets LinkedIn/Cloudflare issue the volatile
ones, and then fetches a profile. A 200 means the service can sustain itself from .env alone.

Usage:
    python3 -m scripts.check_deploy_viability <public-identifier>
"""

import asyncio
import sys

from app.linkedin_client import MOBILE_IMPERSONATE, build_page_headers
from app.session_jar import durable_cookies, new_session


async def main() -> int:
    identifier = sys.argv[1] if len(sys.argv) > 1 else None
    if not identifier:
        print(__doc__)
        return 2

    seeded = durable_cookies()
    print(f"seeding durable cookies only: {sorted(seeded)}")
    print("(no __cf_bm / lidc supplied — the session must earn them)\n")

    headers = {k: v for k, v in build_page_headers().items() if k != "cookie"}

    async with new_session() as session:
        try:
            warm = await session.get(
                "https://www.linkedin.com/",
                headers=headers,
                impersonate=MOBILE_IMPERSONATE,
                timeout=45,
            )
            print(f"warm-up GET / : HTTP {warm.status_code}")
        except Exception as err:  # noqa: BLE001
            print(f"warm-up failed: {type(err).__name__}")
            return 1

        minted = {c.name for c in session.cookies.jar} & {"__cf_bm", "lidc"}
        print(f"volatile cookies minted by the session: {sorted(minted) or 'none'}\n")

        try:
            resp = await session.get(
                f"https://www.linkedin.com/in/{identifier}/",
                headers=headers,
                impersonate=MOBILE_IMPERSONATE,
                timeout=45,
            )
        except Exception as err:  # noqa: BLE001
            print(f"profile fetch failed: {type(err).__name__}")
            print("\nNOT VIABLE — a stale volatile cookie must be replayed manually.")
            return 1

        ok = resp.status_code == 200 and len(resp.text) > 50000
        print(f"profile fetch : HTTP {resp.status_code} ({len(resp.text)} bytes)")
        print()
        print(
            "VIABLE — the service can run from durable cookies in .env alone."
            if ok
            else "NOT VIABLE — durable cookies alone are not accepted."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
