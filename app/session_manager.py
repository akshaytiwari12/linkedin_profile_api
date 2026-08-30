import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any

from . import stores
from .config import config
from .errors import LinkedInAuthError, LinkedInBlockedError, SessionFlaggedError
from .linkedin_client import fetch_profile_html

# Wraps the raw client with the two protections a naive scraper skips:
#
#   1. Pacing with jitter — enforced here rather than per-request so it holds across the whole
#      worker no matter how many jobs queue up.
#   2. A circuit breaker — after repeated auth/block failures we stop entirely instead of
#      pushing an already-flagged session toward a hard account restriction.
#
# Both matter more than they look: an invalidated session logs the account out everywhere and
# can only be recovered by a manual browser login.
_next_available_at = 0.0
_lock = asyncio.Lock()


async def _throttle() -> None:
    global _next_available_at
    async with _lock:
        wait = _next_available_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _next_available_at = (
            time.monotonic()
            + config.min_request_interval_s
            + random.random() * config.request_jitter_s
        )


async def fetch_profile_through_session(public_identifier: str) -> Any:
    health = stores.get_session_health()
    if health["state"] == "flagged":
        raise SessionFlaggedError(health.get("lastError"))

    await _throttle()

    try:
        raw = await fetch_profile_html(public_identifier)
    except (LinkedInAuthError, LinkedInBlockedError) as err:
        failures = health["consecutiveFailures"] + 1
        flagging = failures >= config.session_failure_threshold
        now = datetime.now(timezone.utc).isoformat()
        stores.set_session_health(
            {
                "state": "flagged" if flagging else "healthy",
                "consecutiveFailures": failures,
                "lastError": str(err),
                "lastErrorAt": now,
                "flaggedAt": now if flagging else health.get("flaggedAt"),
                "lastRequestAt": now,
            }
        )
        raise

    stores.set_session_health(
        {
            **health,
            "state": "healthy",
            "consecutiveFailures": 0,
            "lastRequestAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    return raw
