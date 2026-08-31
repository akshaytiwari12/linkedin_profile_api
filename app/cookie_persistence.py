"""Capture the session cookies LinkedIn reissues, so they survive a restart.

LinkedIn rotates `li_at` during an active session — it sends a replacement via `Set-Cookie` and
expects the client to keep it, exactly as a browser would. A service that seeds from
configuration and never writes back throws that replacement away on every restart and goes back
to a token LinkedIn has already superseded, which is a self-inflicted expiry on top of the real
one.

Persisting the rotation means the stored credential tracks whatever LinkedIn last issued, and the
manual step is only needed when LinkedIn actually revokes the session rather than merely renews
it.

Written to DATA_DIR rather than back into .env: the file it would rewrite is also the file a
human edits, and clobbering that during a request is a bad trade for the small convenience.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .config import config

_PATH = os.path.join(config.data_dir, "session-cookies.json")

# Only these are worth persisting: they are the credential. Everything else LinkedIn sets is
# either volatile (__cf_bm, lidc) or telemetry, and stale copies of those cause redirect loops.
PERSISTED = ("li_at", "JSESSIONID", "li_rm")


def load() -> dict[str, str]:
    """Stored cookies, or empty if none have been captured yet."""
    try:
        with open(_PATH, encoding="utf-8") as handle:
            return json.load(handle).get("cookies", {})
    except (OSError, ValueError):
        return {}


def capture(jar: Any) -> dict[str, str]:
    """Persist any rotated credential cookies from a live session jar.

    Returns the cookies that changed, so the caller can log a rotation rather than have it happen
    silently — an unexplained credential change is worth being able to see afterwards.
    """
    current = {c.name: c.value for c in jar if c.name in PERSISTED}
    if not current:
        return {}

    stored = load()
    changed = {k: v for k, v in current.items() if stored.get(k) != v}
    if not changed:
        return {}

    merged = {**stored, **current}
    try:
        os.makedirs(config.data_dir, exist_ok=True)
        tmp = f"{_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(
                {"updatedAt": datetime.now(timezone.utc).isoformat(), "cookies": merged},
                handle,
                indent=2,
            )
        os.replace(tmp, _PATH)
    except OSError:
        # A read-only or full filesystem must not break request handling; the in-memory session
        # still holds the rotated value for the life of this process.
        return {}

    return changed


def effective_credentials() -> tuple[str, str]:
    """The credentials to seed a new session with.

    Prefers a captured rotation over the configured value, since LinkedIn issued it more
    recently. Falls back to configuration when nothing has been captured, or when the operator
    has pasted a new cookie — detected by the stored one no longer matching what LinkedIn
    accepts, which surfaces as an auth failure and a reset.
    """
    stored = load()
    return (
        stored.get("li_at") or config.li_at,
        stored.get("JSESSIONID") or config.jsessionid,
    )


def clear() -> None:
    """Discard captured cookies so the next session uses configuration.

    Called on session reset: if someone has pasted a fresh cookie, a previously captured
    rotation is stale and would otherwise take precedence over the new one.
    """
    try:
        os.remove(_PATH)
    except OSError:
        pass
