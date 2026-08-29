"""Probe the mwlite runQuery surface captured from the mobile web client.

The interesting property of this endpoint: `variables` is empty and the profile being fetched is
identified by the **Referer** header. So targeting an arbitrary profile means varying the referer,
not the body.

Usage:
    python3 -m scripts.probe_mwlite <public-identifier> [more-identifiers...]
"""

import asyncio
import json
import os
import sys
import uuid

from curl_cffi.requests import AsyncSession

from app.config import config

URL = "https://www.linkedin.com/mwlite/profile/api/non-self/runQuery"
QUERY_ID = "da4a9ce2de842c1abe01ca37ea9271ee"
PAGE_KEY = "p_mwlite_profile_view"
PACING_S = 20

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
)


def headers_for(identifier: str) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "cookie": config.cookie_jar
        or f'li_at={config.li_at}; JSESSIONID="{config.jsessionid}"',
        "csrf-token": config.jsessionid,
        "origin": "https://www.linkedin.com",
        # This is what selects the profile — the request body carries no identifier at all.
        "referer": f"https://www.linkedin.com/in/{identifier}/",
        "user-agent": MOBILE_UA,
        "x-requested-with": "XMLHttpRequest",
        "x-referer-pagekey": PAGE_KEY,
        "x-li-page-instance": f"urn:li:page:{PAGE_KEY};{uuid.uuid4()}",
        "x-tracking-id": str(uuid.uuid4()),
        "x-effective-connection-type": "4g",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


async def probe(session: AsyncSession, identifier: str) -> dict | None:
    body = {"queryId": QUERY_ID, "variables": {}, "pageKey": PAGE_KEY}
    try:
        r = await session.post(
            URL,
            headers=headers_for(identifier),
            data=json.dumps(body),
            impersonate="chrome131_android",
            allow_redirects=False,
            timeout=40,
        )
    except Exception as err:  # noqa: BLE001
        print(f"  {identifier}: EXCEPTION {type(err).__name__}: {err}")
        return None

    print(f"  {identifier}: HTTP {r.status_code} ({len(r.content)} bytes)")
    if r.status_code != 200:
        print(f"      body head: {r.text[:200]}")
        return None

    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        print(f"      not JSON: {r.text[:200]}")
        return None

    os.makedirs(config.fixtures_dir, exist_ok=True)
    path = os.path.join(config.fixtures_dir, f"{identifier}.mwlite.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    blob = json.dumps(data)
    print(f"      saved {path}")
    print(f"      top-level keys: {list(data)[:10] if isinstance(data, dict) else type(data)}")
    for probe_word in ("headline", "firstName", "experience", "education", "skill", "certification"):
        print(f"      contains {probe_word!r}: {probe_word.lower() in blob.lower()}")
    return data


async def main() -> int:
    ids = sys.argv[1:]
    if not ids:
        print(__doc__)
        return 2

    async with AsyncSession() as session:
        for i, identifier in enumerate(ids):
            await probe(session, identifier)
            if i < len(ids) - 1:
                await asyncio.sleep(PACING_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
