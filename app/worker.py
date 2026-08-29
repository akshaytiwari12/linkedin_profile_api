import asyncio

from . import stores
from .profile_parser import PARSER_VERSION, parse_profile_view
from .session_manager import fetch_profile_through_session

# One worker draining a queue one job at a time — matching the fact that we are pacing a single
# LinkedIn session. More throughput would mean more sessions in a pool, each with its own loop,
# never more concurrency against one session.
queue: asyncio.Queue[str] = asyncio.Queue()


async def _process(job_id: str) -> None:
    job = stores.get_job(job_id)
    if not job:
        return

    stores.mark_processing(job_id)
    try:
        raw = await fetch_profile_through_session(job["publicIdentifier"])
        raw_record = stores.save_raw_payload(job["publicIdentifier"], raw)
        profile = parse_profile_view(raw, job["publicIdentifier"], job["profileUrl"])
        stores.set_cached(job["publicIdentifier"], profile, PARSER_VERSION, raw_record["id"])
        stores.mark_completed(job_id, profile)
    except Exception as err:  # noqa: BLE001 - failure reason is surfaced to the caller as-is
        stores.mark_failed(job_id, str(err))


async def worker_loop() -> None:
    while True:
        job_id = await queue.get()
        try:
            await _process(job_id)
        finally:
            queue.task_done()
