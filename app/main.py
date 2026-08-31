import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, Path, Query
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import request_log, stores, worker
from . import status_page as status_page_html
from .config import config
from .errors import InvalidProfileUrlError
from .html_parser import PARSER_VERSION, parse_profile_html
from .linkedin_client import reset_session
from .models import (
    ErrorResponse,
    HealthResponse,
    JobAccepted,
    JobStatus,
    LinkedInProfile,
    ResetResponse,
    SessionHealth,
)
from .profile_url import extract_public_identifier

API_DESCRIPTION = """
Accepts a LinkedIn profile URL and returns the profile as structured JSON.

Reaches LinkedIn directly over HTTP — **no browser, no headless Chrome, no automation
framework**. Requests carry a logged-in session cookie and a TLS fingerprint that matches a real
Chrome build, because LinkedIn fingerprints the TLS handshake itself and invalidates sessions
whose handshake looks automated.

### Quick start

    GET /api/profile?url=https://www.linkedin.com/in/some-profile

Use **Try it out** below on `/api/profile` — it is the only endpoint most callers need.

A human-readable service status page, showing session health and recent activity, is at
[`/status`](/status).

### How a request is served

1. The URL is validated as a real `linkedin.com/in/…` address (anything else is rejected).
2. **Cache hit** → returned immediately, no LinkedIn request. `"source": "cache"`.
3. **Cache miss** → a job is queued and briefly awaited, so the call still looks synchronous.
   `"source": "live"`.
4. If LinkedIn is slow, `202` is returned with a `jobId` to poll at `/api/jobs/{id}` rather than
   holding the connection open.

### Rate limiting

Requests to LinkedIn are paced (default ~1 per minute, with jitter) and stop entirely after
repeated auth failures, because an over-used session gets invalidated and can only be restored
by logging in through a browser again. A burst of calls will therefore queue rather than run in
parallel — this is deliberate.

### Fields that are always null

`skills[].endorsementCount` and `certifications[].authority` are not rendered on the surface
this service reads. `about` and `experience[].description` may be truncated to the portion
LinkedIn renders before its "see more" control.

### Authentication

The service authenticates to LinkedIn with cookies supplied as environment variables
(`LI_AT_COOKIE`, `LI_JSESSIONID`). **This API itself is unauthenticated** — anyone who can reach
it can spend the configured session's rate budget. An API key would be the first thing to add
before exposing it publicly.
"""

TAGS_METADATA = [
    {"name": "Profiles", "description": "Fetch and re-parse profile data."},
    {"name": "Jobs", "description": "Poll asynchronous fetches started by `/api/profile`."},
    {
        "name": "Session",
        "description": "Inspect and reset the LinkedIn session's circuit breaker.",
    },
    {"name": "Service", "description": "Liveness."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(worker.worker_loop())
    yield
    task.cancel()


app = FastAPI(
    title="LinkedIn Profile API",
    version="1.0.0",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
    # The stock /docs and /redoc load their assets from cdn.jsdelivr.net, so the page renders
    # blank for anyone whose network blocks that CDN — the server still answers 200, which makes
    # it look like the service is broken. Assets are vendored under app/static and the routes
    # re-declared below so the documentation works on any network, including offline.
    docs_url=None,
    redoc_url=None,
)

_STATIC_DIR = FilePath(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.middleware("http")
async def log_requests(request, call_next):
    """Record every API call and its outcome.

    Reads the identifier and source out of the response body for profile calls so the log says
    *which* profile was requested and whether it came from cache or a live fetch — the two things
    you actually want to know when someone reports "it didn't work". Documentation and static
    asset requests are skipped; they are noise.
    """
    started = asyncio.get_event_loop().time()
    response = await call_next(request)

    path = request.url.path
    if not path.startswith("/api/") and path != "/health":
        return response

    duration_ms = int((asyncio.get_event_loop().time() - started) * 1000)
    identifier = source = error = None

    # Buffer the body so it can be inspected and still be sent to the client.
    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    if path.startswith("/api/profile"):
        try:
            payload = json.loads(body)
            identifier = payload.get("publicIdentifier")
            source = payload.get("source")
            error = payload.get("error")
        except (ValueError, AttributeError):
            pass

    request_log.record(
        path=path,
        status=response.status_code,
        duration_ms=duration_ms,
        identifier=identifier,
        source=source,
        error=error,
    )

    return Response(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.get("/status", include_in_schema=False)
async def status_page() -> HTMLResponse:
    """Human-readable view of the same data as /api/logs, for opening in a browser."""
    return HTMLResponse(
        status_page_html.render(
            session=stores.get_session_health(),
            summary=request_log.summary(),
            requests=request_log.recent(40),
        )
    )


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} — API reference",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_ui() -> HTMLResponse:
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} — reference",
        redoc_js_url="/static/redoc.standalone.js",
    )


@app.get(
    "/health",
    tags=["Service"],
    summary="Liveness check",
    description="Returns `{\"status\": \"ok\"}` if the process is up. Does not contact LinkedIn.",
    response_model=HealthResponse,
)
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


@app.get(
    "/api/profile",
    tags=["Profiles"],
    summary="Get a LinkedIn profile as structured JSON",
    description=(
        "The main endpoint. Pass any LinkedIn profile URL as `url`.\n\n"
        "Accepted forms — all resolve to the same profile:\n\n"
        "- `https://www.linkedin.com/in/some-profile`\n"
        "- `https://www.linkedin.com/in/some-profile/`\n"
        "- `https://in.linkedin.com/in/some-profile?trk=abc`\n"
        "- `linkedin.com/in/some-profile`\n\n"
        "Company pages, feed URLs and non-LinkedIn hosts are rejected with `400`.\n\n"
        "Check the `source` field to see whether the response came from cache or a live fetch. "
        "A cache miss costs one real LinkedIn request and is paced, so it can take a few seconds."
    ),
    response_model=LinkedInProfile,
    responses={
        202: {
            "model": JobAccepted,
            "description": "Fetch still running. Poll `statusUrl` for the result.",
        },
        400: {"model": ErrorResponse, "description": "`url` missing, malformed, or not a profile URL."},
        502: {
            "model": ErrorResponse,
            "description": (
                "The fetch failed — expired session, LinkedIn blocked the request, the profile "
                "does not exist, or the circuit breaker is open. `error` states which."
            ),
        },
    },
)
async def get_profile(
    url: str = Query(
        ...,
        description="Full LinkedIn profile URL.",
        examples=["https://www.linkedin.com/in/some-profile"],
    )
):
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


@app.get(
    "/api/jobs/{job_id}",
    tags=["Jobs"],
    summary="Poll an in-flight fetch",
    description=(
        "Only needed when `/api/profile` returned `202`. Poll every second or so; the profile "
        "arrives in `result` once `status` is `completed`."
    ),
    response_model=JobStatus,
    responses={
        404: {"model": ErrorResponse, "description": "No job with that id."},
        502: {"model": ErrorResponse, "description": "The job failed; `error` states why."},
    },
)
async def get_job(job_id: str = Path(description="Job id returned by `/api/profile`.")):
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


@app.post(
    "/api/profile/{public_identifier}/reparse",
    tags=["Profiles"],
    summary="Re-parse a stored page without contacting LinkedIn",
    description=(
        "Every fetched page is stored before it is parsed. This re-runs the current parser "
        "against the most recently stored page for a profile, so a parser fix can be applied to "
        "already-fetched profiles without spending another LinkedIn request — the scarce and "
        "risky resource here.\n\n"
        "Takes the profile slug, not a full URL: `some-profile`, not the whole link."
    ),
    response_model=LinkedInProfile,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Nothing stored for that profile yet — fetch it via `/api/profile` first.",
        }
    },
)
async def reparse(
    public_identifier: str = Path(
        description="Profile slug, e.g. `some-profile`.", examples=["some-profile"]
    )
):
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


@app.get(
    "/api/session/health",
    tags=["Session"],
    summary="Is the LinkedIn session usable?",
    description=(
        "Reports the circuit breaker. `state: flagged` means repeated auth failures have tripped "
        "it and no further requests will be sent until it is reset — which is deliberate: "
        "continuing to hammer a rejected session is what escalates a logout into an account "
        "restriction."
    ),
    response_model=SessionHealth,
)
async def session_health():
    return stores.get_session_health()


@app.get(
    "/api/logs",
    tags=["Session"],
    summary="Recent requests and their outcomes",
    description=(
        "What has been called, whether it worked, and why it didn't — without needing shell "
        "access to the host.\n\n"
        "Records the profile identifier and the outcome, never the profile data itself. Covers "
        "the current process only: a restart clears it, and on hosts with an ephemeral "
        "filesystem so does a redeploy.\n\n"
        "`outcome` is the field to scan: `ok (live)`, `ok (cache)`, `queued`, "
        "`linkedin session rejected`, `fetch failed`, `bad request`."
    ),
)
async def get_logs(
    limit: int = Query(50, ge=1, le=200, description="How many recent entries to return.")
):
    return {"summary": request_log.summary(), "requests": request_log.recent(limit)}


@app.post(
    "/api/session/reset",
    tags=["Session"],
    summary="Clear the circuit breaker after refreshing cookies",
    description=(
        "Call after updating `LI_AT_COOKIE` / `LI_JSESSIONID`. Clears the failure count and drops "
        "the cached HTTP session so the next request re-warms with the new cookies."
    ),
    response_model=ResetResponse,
)
async def session_reset():
    stores.reset_session_health()
    await reset_session()
    return {"status": "reset"}
