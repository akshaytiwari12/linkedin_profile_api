# LinkedIn Profile API

A hosted HTTP API that accepts a LinkedIn profile URL and returns most of the information on
that profile as structured JSON. It works by calling LinkedIn's own internal `voyager` API
endpoints directly (no browser, no headless Chrome) — the same endpoints LinkedIn's web app
calls under the hood — authenticated with a logged-in session cookie.

## Approach

LinkedIn does not offer a public API for reading arbitrary profile data. Instead of driving a
browser, this service reverse-engineers LinkedIn's internal REST API (`/voyager/api/...`), which
returns structured JSON directly — no HTML scraping needed.

The naive version of this (call the endpoint synchronously on every request) has three real
problems: every request burns LinkedIn rate budget even for repeat lookups, client latency
becomes a direct function of LinkedIn's mood, and one schema change breaks everything with no way
to recover already-fetched data. This service is instead built as a small **pipeline** that
separates fetching (expensive, risky, rate-limited) from serving (cheap, should be instant):

```
Client → API Gateway → Result Cache (hit?) → return immediately
                     → (miss) → Job Queue → Worker → Session Manager → LinkedIn
                                    ↓
                          Raw Payload Store (immutable)
                                    ↓
                          Normalizer (versioned) → Result Cache
```

1. **Auth**: a real LinkedIn session is captured once (see Setup) and supplied to the server as
   two cookie values: `li_at` (the session token) and `JSESSIONID` (also used as the CSRF token
   LinkedIn requires on `voyager` requests).
2. **API Gateway** (`src/server.ts`): `GET /api/profile?url=...` checks the result cache first —
   a hit returns instantly, no LinkedIn call. A miss enqueues a fetch job and briefly long-polls
   it (`LONG_POLL_TIMEOUT_MS`, default 8s), so most cache-miss requests still look synchronous.
   If the job hasn't finished by then, it returns `202` with a `jobId` to poll via
   `GET /api/jobs/:id` instead of holding the connection open indefinitely.
3. **Job Queue + Worker** (`src/queue/`, `src/worker.ts`): an in-process FIFO queue with a single
   worker that processes jobs one at a time. This is where request *pacing* is enforced,
   independent of how many requests arrive — see Session Manager below.
4. **Session Manager** (`src/sessionManager.ts`): wraps the raw LinkedIn call with (a) rate
   limiting — a minimum interval plus random jitter between real LinkedIn requests, so the
   pattern looks like a human browsing rather than a script firing on demand — and (b) a
   **circuit breaker** — after `SESSION_FAILURE_THRESHOLD` consecutive auth/block failures, it
   stops sending further requests entirely (`SessionFlaggedError`) instead of hammering an
   already-flagged or dead session towards a permanent ban. Reset it via
   `POST /api/session/reset` after refreshing the cookie.
5. **Fetch**: `GET /voyager/api/identity/profiles/{publicIdentifier}/profileView` with the
   session cookie, CSRF token, and headers that mirror what a browser sends
   (`x-restli-protocol-version`, `accept`, `user-agent`, etc). A 3xx (LinkedIn redirecting to its
   login page) is treated as an auth failure rather than followed.
6. **Raw Payload Store** (`src/store/rawPayloadStore.ts`): every successful raw response is
   persisted, immutably, before parsing. This is what makes the pipeline resilient to LinkedIn's
   schema drift: if `profileView`'s shape changes and breaks the parser, fix the parser and
   **replay it against already-stored payloads** via `POST /api/profile/:id/reparse` — zero
   additional LinkedIn requests needed to recover already-fetched profiles.
7. **Normalizer** (`src/profileParser.ts`): `profileView` responses are a flat, typed entity list
   (`included: [...]`), not a single nested profile object — each entity carries a `$type` such
   as `com.linkedin.voyager.identity.profile.Position` or `...Education`. The parser filters this
   list by type and reshapes it into the response schema below. It's a pure function
   (`rawPayload → LinkedInProfile`) tagged with a `PARSER_VERSION`, so cached/stored records are
   traceable to the parser version that produced them.
8. **Result Cache** (`src/store/resultCache.ts`): the parsed profile is cached with a TTL
   (`CACHE_TTL_HOURS`, default 48h). This is what turns "N requests for the same popular profile"
   into one LinkedIn hit instead of N — directly reducing detection risk, not just latency.

All storage (raw payloads, cached results, jobs, session health) is a small dependency-free
JSON-file store (`src/store/jsonTable.ts`) under `data/` — no external DB/queue/cache service to
stand up. Each store is written behind a narrow interface so it can be swapped for
SQLite/Postgres/Redis without touching the rest of the pipeline if this needed to run as more
than one process.

## Setup

### 1. Get a LinkedIn session

You need to be logged into LinkedIn in a real browser with the account you're willing to use for
this service (see Known Limitations re: account risk).

1. Log into linkedin.com in Chrome/Firefox.
2. Open DevTools → Application (Chrome) / Storage (Firefox) → Cookies → `https://www.linkedin.com`.
3. Copy the value of the `li_at` cookie.
4. Copy the value of the `JSESSIONID` cookie, **including the surrounding double quotes**
   (LinkedIn stores it as `"ajax:1234567890123456789"`).

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```
LI_AT_COOKIE=<your li_at value>
LI_JSESSIONID="ajax:...your JSESSIONID value..."
PORT=3000
```

`.env` is gitignored — never commit real credentials.

Optional tuning (sane defaults if omitted — see `src/config.ts`):

| Var | Default | What it controls |
| --- | --- | --- |
| `DATA_DIR` | `data` | Where the JSON-file store lives |
| `CACHE_TTL_HOURS` | `48` | How long a parsed profile stays cached before re-fetching |
| `MIN_REQUEST_INTERVAL_MS` | `4000` | Minimum spacing between real LinkedIn requests |
| `REQUEST_JITTER_MS` | `3000` | Random jitter added on top of the min interval |
| `SESSION_FAILURE_THRESHOLD` | `2` | Consecutive failures before the circuit breaker trips |
| `LONG_POLL_TIMEOUT_MS` | `8000` | How long `/api/profile` waits before falling back to `202` |

### 3. Install and run

```bash
npm install
npm run dev     # local development, auto-reload
# or
npm run build && npm start   # production
```

### 4. Deploy

Deploy anywhere that runs a Node process (Render, Railway, Fly.io, etc.). Set `LI_AT_COOKIE`,
`LI_JSESSIONID`, and `PORT` as platform environment variables/secrets — never in code or in the
repo.

## API

### `GET /health`

Liveness check.

```json
{ "status": "ok" }
```

### `GET /api/profile?url=<linkedin-profile-url>`

Accepts any LinkedIn profile URL, e.g. `https://www.linkedin.com/in/john-doe/`.

- **Cache hit** → `200 OK` immediately, `"source": "cache"`, plus `cachedAt`/`expiresAt`.
- **Cache miss, job finishes within the long-poll window** → `200 OK`, `"source": "live"`.
- **Cache miss, job still running after the long-poll window** → `202 Accepted`:
  ```json
  { "jobId": "...", "status": "processing", "statusUrl": "/api/jobs/..." }
  ```
  Poll `statusUrl` until `status` is `completed` (returns `result`) or `failed` (returns `error`).

**Success — `200 OK`**

```json
{
  "publicIdentifier": "john-doe",
  "profileUrl": "https://www.linkedin.com/in/john-doe/",
  "firstName": "John",
  "lastName": "Doe",
  "fullName": "John Doe",
  "headline": "Software Engineer at Example Corp",
  "location": "San Francisco, California, United States",
  "about": "...",
  "profileImages": [
    { "url": "https://media.licdn.com/...", "width": 400, "height": 400 }
  ],
  "experience": [
    {
      "title": "Software Engineer",
      "companyName": "Example Corp",
      "location": "San Francisco, CA",
      "description": "...",
      "startDate": { "month": 1, "year": 2022 },
      "endDate": null,
      "isCurrent": true
    }
  ],
  "education": [
    {
      "schoolName": "Example University",
      "degreeName": "B.S.",
      "fieldOfStudy": "Computer Science",
      "startYear": 2016,
      "endYear": 2020,
      "description": null
    }
  ],
  "skills": [{ "name": "TypeScript", "endorsementCount": 12 }],
  "certifications": [
    {
      "name": "AWS Certified Developer",
      "authority": "Amazon Web Services",
      "startDate": { "month": 6, "year": 2023 },
      "endDate": null
    }
  ],
  "languages": [{ "name": "English", "proficiency": "Native or bilingual" }],
  "fetchedAt": "2026-08-29T12:00:00.000Z"
}
```

**Error responses**

| Status | Meaning |
| --- | --- |
| 400 | `url` missing or not a recognizable LinkedIn profile URL |
| 404 | No job found for that id (`/api/jobs/:id` only) |
| 502 | The fetch job failed — LinkedIn session invalid/expired, profile not found, LinkedIn flagged the request, or the circuit breaker is open. `error` has the specific reason. |
| 500 | Unexpected error |

### `GET /api/jobs/:id`

Poll a job created by a `202` from `/api/profile`.

```json
{ "id": "...", "status": "completed", "result": { /* LinkedInProfile */ }, "updatedAt": "..." }
```

`status` is one of `queued` | `processing` | `completed` | `failed`.

### `POST /api/profile/:publicIdentifier/reparse`

Re-runs the current parser against the most recently stored raw payload for that profile —
no LinkedIn request. Useful right after fixing/improving the parser. `404` if nothing has been
fetched for that identifier yet.

### `GET /api/session/health`

```json
{ "state": "healthy", "consecutiveFailures": 0, "lastError": null, "flaggedAt": null, "lastRequestAt": "..." }
```

### `POST /api/session/reset`

Clears the circuit breaker after you've refreshed `LI_AT_COOKIE`/`LI_JSESSIONID` and restarted
the server. `{ "status": "reset" }`.

## Known limitations

- **This violates LinkedIn's Terms of Service.** Automated access to non-public API endpoints is
  against LinkedIn's User Agreement. Using it risks the backing account being rate-limited,
  challenged (CAPTCHA/email verification), or restricted. This project exists to demonstrate the
  reverse-engineering approach, not as a production-safe integration.
- **Session lifetime is unpredictable.** `li_at` is nominally long-lived (~1 year), but LinkedIn
  invalidates it early on password changes, "sign out of all devices," or anomaly detection
  (server IP, TLS/header fingerprint, or request cadence differing from a real browser). There is
  no way to refresh it without a browser login — expect to manually re-capture the cookie
  periodically.
- **Single session, no rotation.** Rate limiting and the circuit breaker protect the one
  configured account from being hammered, but there's no pool of sessions to fall back to — once
  the circuit breaker trips, the service is down until someone manually refreshes the cookie and
  calls `/api/session/reset`. Not built for high-volume use.
- **Undocumented, unstable response schema.** The `voyager` API is LinkedIn's internal API, not a
  public contract — field names and entity `$type`s have changed between LinkedIn releases in the
  past and may change again without notice. The raw-payload store + `/reparse` limits the damage
  (fix the parser, replay stored data, no re-fetch needed) but doesn't prevent the breakage itself.
- **Partial data by design.** Fields the requested profile has set to a privacy level the
  requesting account can't see (e.g. connections-only) will come back `null`/empty rather than
  causing an error.
- **Single profileView call.** Some data (e.g. verified contact info/email) lives behind a
  separate `contactInfo` endpoint not currently called; only what `profileView` returns is
  parsed.
- **JSON-file store, not a real database.** Fine for the single-process, moderate-volume scope of
  this project; it is not safe for multiple server processes writing concurrently (no cross-process
  locking) and has no query capability beyond exact-key lookup. The store modules are written
  behind small interfaces specifically so swapping in SQLite/Postgres/Redis later doesn't touch
  the pipeline logic.
- **Long-poll, not push.** Clients waiting past `LONG_POLL_TIMEOUT_MS` have to poll
  `/api/jobs/:id` themselves; there's no webhook/SSE notification on completion.
