"""Liveness check for the configured session. Touches only /voyager/api/me — the caller's own
account — and prints a status code, nothing else.

Usage:
    python3 -m scripts.check_session
"""

import asyncio

from curl_cffi.requests import AsyncSession

from app.config import config
from app.linkedin_client import BASE_URL, build_headers


async def main() -> int:
    async with AsyncSession() as session:
        try:
            r = await session.get(
                f"{BASE_URL}/me",
                headers=build_headers(),
                impersonate=config.impersonate,
                allow_redirects=False,
                timeout=30,
            )
        except Exception as err:  # noqa: BLE001
            print(f"EXCEPTION {type(err).__name__}: {err}")
            return 1

    print(f"/voyager/api/me -> HTTP {r.status_code} ({len(r.content)} bytes)")
    if r.status_code == 200:
        print("SESSION ALIVE")
    elif 300 <= r.status_code < 400:
        print("SESSION DEAD (redirected to login) — capture fresh cookies from the browser")
    else:
        print("UNEXPECTED — see status above")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
