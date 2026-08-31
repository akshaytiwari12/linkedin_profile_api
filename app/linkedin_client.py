import asyncio
import json
from typing import Any

from curl_cffi.requests import AsyncSession

from . import cookie_persistence
from .config import config
from .errors import LinkedInAuthError, LinkedInBlockedError, ProfileNotFoundError
from .session_jar import new_session

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
        # voyager identifies its own web client with this; requests without it look like they
        # came from something that isn't the LinkedIn SPA. Observed verbatim in browser traffic.
        "x-li-track": json.dumps(
            {
                "clientVersion": "1.13.46267",
                "mpVersion": "1.13.46267",
                "osName": "web",
                "timezoneOffset": 5.5,
                "timezone": "Asia/Calcutta",
                "deviceFormFactor": "DESKTOP",
                "mpName": "voyager-web",
                "displayDensity": 2,
                "displayWidth": 2560,
                "displayHeight": 1440,
            },
            separators=(",", ":"),
        ),
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
    """Legacy voyager JSON fetch. Retained for reference — LinkedIn now answers this endpoint
    with 410 Gone. fetch_profile_html is the live path."""
    try:
        return await voyager_get(f"/identity/profiles/{public_identifier}/profileView")
    except ProfileNotFoundError:
        raise ProfileNotFoundError(public_identifier) from None


# LinkedIn serves the lightweight mobile-web ("mwlite") profile to mobile clients, and unlike
# the desktop app it server-renders the whole profile into the HTML rather than fetching it
# client-side. That makes it the only surface that still returns profile data to a single
# no-browser request.
# The user-agent, the client hints and the TLS impersonation target must all describe the same
# browser. Anti-bot systems cross-check them, and a handshake announcing one Chrome version while
# the header claims another is a stronger signal than either would be alone. These values are
# taken verbatim from real browser traffic against LinkedIn.
_CHROME_MAJOR = "129"
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{_CHROME_MAJOR}.0.0.0 Mobile Safari/537.36"
)
_SEC_CH_UA = (
    f'"Google Chrome";v="{_CHROME_MAJOR}", "Not=A?Brand";v="8", '
    f'"Chromium";v="{_CHROME_MAJOR}"'
)
MOBILE_IMPERSONATE = "chrome131_android"


def build_page_headers() -> dict[str, str]:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "cookie": config.cookie_jar
        or f'li_at={config.li_at}; JSESSIONID="{config.jsessionid}"',
        "user-agent": MOBILE_UA,
        # Real Chrome always sends these; their absence is as noticeable as a wrong value.
        "sec-ch-ua": _SEC_CH_UA,
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-prefers-color-scheme": "light",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "upgrade-insecure-requests": "1",
    }


# One long-lived session for the process, seeded with durable cookies only.
#
# The volatile cookies (__cf_bm, lidc) must not come from configuration: __cf_bm expires after
# 30 minutes of inactivity, so a service replaying the value captured at setup would serve for
# half an hour and then redirect-loop forever. Holding the session lets LinkedIn and Cloudflare
# issue those cookies and refresh them via Set-Cookie, which is what makes unattended operation
# possible at all (verified by scripts/check_deploy_viability.py).
_session: AsyncSession | None = None
_session_lock = asyncio.Lock()


async def _get_session() -> AsyncSession:
    global _session
    async with _session_lock:
        if _session is None:
            session = new_session()
            headers = {k: v for k, v in build_page_headers().items() if k != "cookie"}
            try:
                # One warm-up so the volatile cookies exist before the first profile request.
                await session.get(
                    "https://www.linkedin.com/",
                    headers=headers,
                    impersonate=MOBILE_IMPERSONATE,
                    timeout=45,
                )
            except Exception:  # noqa: BLE001 - a failed warm-up is not fatal; the fetch will report
                pass
            _session = session
        return _session


async def reset_session() -> None:
    """Drop the cached session so the next request re-warms with fresh cookies from config."""
    global _session
    async with _session_lock:
        _session = None


async def fetch_profile_html(public_identifier: str) -> str:
    """Fetch a profile page as HTML. Returns the raw markup for the parser."""
    kwargs: dict[str, Any] = {}
    if config.proxy:
        kwargs["proxies"] = {"http": config.proxy, "https": config.proxy}

    session = await _get_session()
    headers = {k: v for k, v in build_page_headers().items() if k != "cookie"}

    try:
        response = await session.get(
            f"https://www.linkedin.com/in/{public_identifier}/",
            headers=headers,
            impersonate=MOBILE_IMPERSONATE,
            allow_redirects=True,
            timeout=45,
            **kwargs,
        )
    except Exception as err:  # noqa: BLE001
        # A dead session bounces between the profile page and the login wall until the
        # redirect limit trips, so an exhausted redirect chain means auth, not a network fault.
        if "redirect" in str(err).lower():
            raise LinkedInAuthError() from err
        raise

    if response.status_code in (401, 403):
        raise LinkedInAuthError()
    if response.status_code in (429, 999):
        raise LinkedInBlockedError()
    if response.status_code == 404:
        raise ProfileNotFoundError(public_identifier)
    if response.status_code != 200:
        raise RuntimeError(f"LinkedIn request failed: {response.status_code}")

    html = response.text
    if "authwall" in html.lower() or len(html) < 20000:
        raise LinkedInAuthError("LinkedIn served an auth wall instead of the profile.")

    # LinkedIn rotates li_at mid-session; keep whatever it just issued so a restart does not
    # revert to a superseded token.
    rotated = cookie_persistence.capture(session.cookies.jar)
    if rotated:
        print(f"[session] LinkedIn rotated: {sorted(rotated)}", flush=True)

    return html
