import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import config
from .json_table import JsonTable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Raw payload store -------------------------------------------------------------------
# Immutable log of every raw LinkedIn response, persisted *before* parsing. Decouples fetching
# from parsing: when LinkedIn shifts its schema and breaks the parser, fix the parser and replay
# it against stored payloads instead of spending more LinkedIn requests to recover.
_raw = JsonTable[dict[str, Any]](os.path.join(config.data_dir, "raw-payloads.json"))


def save_raw_payload(public_identifier: str, raw: Any) -> dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "publicIdentifier": public_identifier,
        "fetchedAt": _now(),
        "raw": raw,
    }
    _raw.set(record["id"], record)
    return record


def latest_raw_payload_for(public_identifier: str) -> dict[str, Any] | None:
    matches = [r for r in _raw.values() if r["publicIdentifier"] == public_identifier]
    matches.sort(key=lambda r: r["fetchedAt"], reverse=True)
    return matches[0] if matches else None


# --- Result cache ------------------------------------------------------------------------
# TTL'd cache of parsed profiles. Turns N requests for the same profile into one LinkedIn hit,
# which reduces detection risk as much as it reduces latency.
_cache = JsonTable[dict[str, Any]](os.path.join(config.data_dir, "result-cache.json"))


def get_cached(public_identifier: str) -> dict[str, Any] | None:
    record = _cache.get(public_identifier)
    if not record:
        return None
    if datetime.fromisoformat(record["expiresAt"]) < datetime.now(timezone.utc):
        return None
    return record


def set_cached(
    public_identifier: str, profile: dict[str, Any], parser_version: int, raw_payload_id: str
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    record = {
        "publicIdentifier": public_identifier,
        "profile": profile,
        "parserVersion": parser_version,
        "rawPayloadId": raw_payload_id,
        "cachedAt": now.isoformat(),
        "expiresAt": (now + timedelta(hours=config.cache_ttl_hours)).isoformat(),
    }
    _cache.set(public_identifier, record)
    return record


# --- Job store ---------------------------------------------------------------------------
_jobs = JsonTable[dict[str, Any]](os.path.join(config.data_dir, "jobs.json"))


def create_job(public_identifier: str, profile_url: str) -> dict[str, Any]:
    now = _now()
    job = {
        "id": str(uuid.uuid4()),
        "publicIdentifier": public_identifier,
        "profileUrl": profile_url,
        "status": "queued",
        "createdAt": now,
        "updatedAt": now,
    }
    _jobs.set(job["id"], job)
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def find_active_job_for(public_identifier: str) -> dict[str, Any] | None:
    """Collapses concurrent requests for the same profile onto one LinkedIn fetch."""
    for job in _jobs.values():
        if job["publicIdentifier"] == public_identifier and job["status"] in ("queued", "processing"):
            return job
    return None


def _update_job(job_id: str, **fields: Any) -> None:
    job = _jobs.get(job_id)
    if not job:
        return
    _jobs.set(job_id, {**job, **fields, "updatedAt": _now()})


def mark_processing(job_id: str) -> None:
    _update_job(job_id, status="processing")


def mark_completed(job_id: str, result: dict[str, Any]) -> None:
    _update_job(job_id, status="completed", result=result)


def mark_failed(job_id: str, error: str) -> None:
    _update_job(job_id, status="failed", error=error)


# --- Session health ----------------------------------------------------------------------
_health = JsonTable[dict[str, Any]](os.path.join(config.data_dir, "session-health.json"))
_HEALTH_KEY = "default"  # single session today; keyed for a future session pool.

_INITIAL_HEALTH = {
    "state": "healthy",
    "consecutiveFailures": 0,
    "lastError": None,
    "lastErrorAt": None,
    "flaggedAt": None,
    "lastRequestAt": None,
}


def get_session_health() -> dict[str, Any]:
    return _health.get(_HEALTH_KEY) or dict(_INITIAL_HEALTH)


def set_session_health(record: dict[str, Any]) -> None:
    _health.set(_HEALTH_KEY, record)


def reset_session_health() -> None:
    _health.set(_HEALTH_KEY, dict(_INITIAL_HEALTH))
