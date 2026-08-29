"""Cookie handling for LinkedIn requests.

LinkedIn's cookie jar splits into two classes, and conflating them is what causes the
"worked 20 minutes ago, redirect-loops now" failure:

  durable  — li_at, JSESSIONID, bcookie, liap. Long-lived identity/session cookies. These are
             what belongs in .env.
  volatile — __cf_bm (Cloudflare bot management, expires after 30 min of inactivity) and lidc
             (LinkedIn datacenter routing, carries an embedded expiry). These are *issued* by
             LinkedIn/Cloudflare per session.

Replaying a stale volatile cookie is worse than sending none: the server tries to re-issue it,
we keep presenting the expired one, and the two sides bounce until the redirect limit trips.
__cf_bm in particular is encrypted and only Cloudflare can decrypt it, so it cannot be forged —
it has to be earned by making a request and keeping what comes back.

So: seed a live session with the durable cookies only, then let the session collect the volatile
ones from Set-Cookie responses.
"""

from curl_cffi.requests import AsyncSession

from .config import config

# Cookies we deliberately never replay from configuration.
VOLATILE = {"__cf_bm", "lidc", "df_ts", "UserMatchHistory", "sdui_ver"}

DURABLE_ALLOWLIST = {"li_at", "JSESSIONID", "bcookie", "bscookie", "liap", "lang", "li_theme"}


def durable_cookies() -> dict[str, str]:
    """Durable cookies to seed a session with.

    Uses LI_COOKIE_JAR when provided (filtered down to the durable set), otherwise falls back to
    the two cookies the voyager API needs.
    """
    cookies = {
        "li_at": config.li_at,
        # LinkedIn stores this wrapped in literal double quotes; the cookie keeps them even
        # though the csrf-token header must not have them.
        "JSESSIONID": f'"{config.jsessionid}"',
    }

    if config.cookie_jar:
        for part in config.cookie_jar.split(";"):
            if "=" not in part:
                continue
            name, _, value = part.strip().partition("=")
            if name in VOLATILE:
                continue
            if name in DURABLE_ALLOWLIST:
                cookies[name] = value

    return cookies


def new_session() -> AsyncSession:
    """A session seeded with durable cookies that will accumulate volatile ones itself."""
    return AsyncSession(cookies=durable_cookies())
