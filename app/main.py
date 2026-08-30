import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import stores, worker
from .config import config
from .errors import InvalidProfileUrlError
from .html_parser import PARSER_VERSION, parse_profile_html
from .profile_url import extract_public_identifier


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(worker.worker_loop())
    yield
    task.cancel()


app = FastAPI(
    title="LinkedIn Profile API",
    description="Reverse-engineered LinkedIn profile data as structured JSON.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _wait_for_job(job_id: str) -> dict:
    """Briefly polls the job so a cache miss still looks synchronous when LinkedIn answers
    quickly; past the window the caller gets a job id to poll instead of a hung connection."""
    deadline = asyncio.get_event_loop().time() + config.long_poll_timeout_s
    job = stores.get_job(job_id)
    while (
        job
        and job["status"] in ("queued", "processing")
        and asyncio.get_event_loop().time() < deadline
    ):
        await asyncio.sleep(config.long_poll_interval_s)
        job = stores.get_job(job_id)
    return job or {}


@app.get("/api/profile")
async def get_profile(url: str = Query(..., description="LinkedIn profile URL")):
    try:
        public_identifier = extract_public_identifier(url)
    except InvalidProfileUrlError as err:
        return JSONResponse(status_code=400, content={"error": str(err)})

    cached = stores.get_cached(public_identifier)
    if cached:
        return {
            **cached["profile"],
            "source": "cache",
            "cachedAt": cached["cachedAt"],
            "expiresAt": cached["expiresAt"],
        }

    job = stores.find_active_job_for(public_identifier)
    if not job:
        job = stores.create_job(public_identifier, url)
        await worker.queue.put(job["id"])

    job = await _wait_for_job(job["id"])

    if job.get("status") == "completed":
        return {**job["result"], "source": "live"}
    if job.get("status") == "failed":
        return JSONResponse(
            status_code=502, content={"error": job.get("error"), "jobId": job.get("id")}
        )

    return JSONResponse(
        status_code=202,
        content={
            "jobId": job.get("id"),
            "status": job.get("status"),
            "statusUrl": f"/api/jobs/{job.get('id')}",
        },
    )


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = stores.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": f'No job found with id "{job_id}".'})
    if job["status"] == "failed":
        return JSONResponse(
            status_code=502,
            content={"id": job["id"], "status": job["status"], "error": job.get("error")},
        )
    if job["status"] == "completed":
        return {
            "id": job["id"],
            "status": job["status"],
            "result": job.get("result"),
            "updatedAt": job["updatedAt"],
        }
    return {"id": job["id"], "status": job["status"], "updatedAt": job["updatedAt"]}


@app.post("/api/profile/{public_identifier}/reparse")
async def reparse(public_identifier: str):
    """Re-normalizes the latest stored raw payload through the current parser — no LinkedIn
    request. This is the payoff of storing raw responses separately from parsed ones."""
    record = stores.latest_raw_payload_for(public_identifier)
    if not record:
        return JSONResponse(
            status_code=404,
            content={
                "error": f'No stored raw payload for "{public_identifier}" yet — '
                "fetch it via /api/profile first."
            },
        )

    profile_url = f"https://www.linkedin.com/in/{public_identifier}/"
    profile = parse_profile_html(record["raw"], public_identifier, profile_url)
    stores.set_cached(public_identifier, profile, PARSER_VERSION, record["id"])
    return {**profile, "source": "reparsed"}


@app.get("/api/session/health")
async def session_health():
    return stores.get_session_health()


@app.post("/api/session/reset")
async def session_reset():
    stores.reset_session_health()
    return {"status": "reset"}
