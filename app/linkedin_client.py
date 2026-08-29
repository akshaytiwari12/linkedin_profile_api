from typing import Any

from curl_cffi.requests import AsyncSession

from .config import config
from .errors import LinkedInAuthError, LinkedInBlockedError, ProfileNotFoundError

BASE_URL = "https://www.linkedin.com/voyager/api"


def build_headers() -> dict[str, str]:
    """Header/cookie format below was determined empirically against the live API — both
    quoting details matter and getting either wrong yields a 302 to the login page:

      * the JSESSIONID *cookie* must keep its surrounding double quotes
      * the csrf-token *header* must NOT have them

    (Verified: quoted cookie + unquoted csrf -> 200; any other combination -> 302.)
    """
    return {
        # The voyager API accepts just li_at + JSESSIONID, but other LinkedIn surfaces expect
        # the wider jar a real browser sends (bcookie/lidc/__cf_bm/...). Prefer the full jar
        # when one is configured.
        "cookie": config.cookie_jar
        or f'li_at={config.li_at}; JSESSIONID="{config.jsessionid}"',
        "csrf-token": config.jsessionid,
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
        "referer": "https://www.linkedin.com/",
    }


async def voyager_get(path: str) -> Any:
    kwargs: dict[str, Any] = {}
    if config.proxy:
        # Must be a *sticky* session proxy — LinkedIn invalidates a session whose IP changes
        # mid-flight, so a rotating pool is worse than no proxy at all here.
        kwargs["proxies"] = {"http": config.proxy, "https": config.proxy}

    async with AsyncSession() as session:
        response = await session.get(
            f"{BASE_URL}{path}",
            headers=build_headers(),
            **kwargs,
            # Presents a real Chrome TLS/JA3 + HTTP2 fingerprint. Without this LinkedIn sees a
            # valid session cookie arriving over an automation-shaped handshake, reads it as a
            # stolen session, and invalidates it globally. This is the single most important
            # line in the project — see README "Approach".
            impersonate=config.impersonate,
            # An expired/rejected session is answered with a redirect to the login page, not a
            # 401 — don't follow it into an HTML page, treat it as an auth failure.
            allow_redirects=False,
            timeout=30,
        )

    if 300 <= response.status_code < 400:
        raise LinkedInAuthError()
    if response.status_code in (401, 403):
        raise LinkedInAuthError()
    if response.status_code in (429, 999):
        raise LinkedInBlockedError()
    if response.status_code == 404:
        raise ProfileNotFoundError(path)
    if response.status_code >= 400:
        raise RuntimeError(f"LinkedIn request failed: {response.status_code}")

    return response.json()


async def fetch_profile_view(public_identifier: str) -> Any:
    try:
        return await voyager_get(f"/identity/profiles/{public_identifier}/profileView")
    except ProfileNotFoundError:
        raise ProfileNotFoundError(public_identifier) from None
