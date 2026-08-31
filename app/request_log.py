"""Request log — what was called, whether it worked, and why it didn't.

Two outputs, because they answer different questions:

  * a structured line on stdout, which is what a hosting dashboard shows and what survives a
    container restart;
  * a bounded in-memory + on-disk ring buffer readable through `GET /api/logs`, so the same
    information is available without shell access to the host.

Deliberately records the profile *identifier* and the outcome, never the profile data itself —
the point is to know whether a request succeeded, not to keep a second copy of everyone's
personal information in a log file.
"""

from __future__ import annotations

import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque

from .config import config

MAX_ENTRIES = 200

_entries: Deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
_log_path = os.path.join(config.data_dir, "requests.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    *,
    path: str,
    status: int,
    duration_ms: int,
    identifier: str | None = None,
    source: str | None = None,
    error: str | None = None,
) -> None:
    """Record one handled request.

    `outcome` collapses the detail into something scannable: a reader wants to know at a glance
    whether the service is serving, falling back to cache, or failing on authentication.
    """
    if status == 200:
        outcome = f"ok ({source})" if source else "ok"
    elif status == 202:
        outcome = "queued"
    elif status == 400:
        outcome = "bad request"
    elif status == 401 or (error and "session" in error.lower()):
        outcome = "linkedin session rejected"
    elif status == 502:
        outcome = "fetch failed"
    else:
        outcome = f"http {status}"

    entry = {
        "at": _now(),
        "path": path,
        "status": status,
        "durationMs": duration_ms,
        "outcome": outcome,
    }
    if identifier:
        entry["profile"] = identifier
    if source:
        entry["source"] = source
    if error:
        # Truncated: the useful part of these messages is at the front, and a full traceback in
        # a log endpoint is noise.
        entry["error"] = error[:200]

    _entries.append(entry)

    # stdout, so it appears in the hosting platform's log stream
    print(f"[request] {json.dumps(entry, separators=(',', ':'))}", file=sys.stdout, flush=True)

    try:
        os.makedirs(config.data_dir, exist_ok=True)
        with open(_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        # A read-only or full filesystem must not break request handling; stdout already has it.
        pass


def recent(limit: int = 50) -> list[dict[str, Any]]:
    """Most recent entries, newest first."""
    return list(_entries)[-limit:][::-1]


def summary() -> dict[str, Any]:
    """Aggregate counts, so 'is it working?' is answerable without reading every line."""
    total = len(_entries)
    by_outcome: dict[str, int] = {}
    for entry in _entries:
        by_outcome[entry["outcome"]] = by_outcome.get(entry["outcome"], 0) + 1

    profile_calls = [e for e in _entries if e["path"].startswith("/api/profile")]
    return {
        "recorded": total,
        "capacity": MAX_ENTRIES,
        "profileRequests": len(profile_calls),
        "byOutcome": by_outcome,
        "lastRequestAt": _entries[-1]["at"] if _entries else None,
        "note": "Counts cover this process only; restarting the service clears them.",
    }
