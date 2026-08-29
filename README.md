# LinkedIn Profile API

An HTTP API that accepts a LinkedIn profile URL and returns the profile as structured JSON. It
calls LinkedIn's internal `voyager` API directly — **no browser, no headless Chrome, no DOM
scraping** — authenticated with a logged-in session cookie and a TLS fingerprint that matches a
real browser.

```bash
curl "https://<host>/api/profile?url=https://www.linkedin.com/in/john-doe"
```

---

## Approach

LinkedIn has no public API for reading arbitrary profile data. The interesting part of this
problem isn't finding an endpoint — it's staying authenticated once you do. Three findings
shaped the design, each established empirically against the live API rather than assumed.

### Finding 1 — voyager still works, but the browser no longer reveals it

Observing linkedin.com in DevTools today shows **no** `voyager` calls. The profile page loads
through React Server Components (`POST /flagship-web/rsc-action/actions/component`). It's easy
to conclude from this that the voyager API is gone and that you must reverse-engineer the RSC
protocol.

That conclusion is wrong. Under RSC the data flow became:

```
browser → rsc-action → LinkedIn's BFF server → voyager (server-to-server) → RSC payload → browser
```

Voyager didn't disappear; it moved *behind* LinkedIn's own server where DevTools can't see it.
A direct request confirms it still accepts cookie auth and returns clean JSON:

```
GET /voyager/api/me   →  200  {"data":{"plainId":...,"$type":"com.linkedin.voyager..."}}
```

So this service targets voyager, not RSC. That matters: the RSC route would mean parsing React's
internal "flight" stream format and tracking build-hash action IDs that rotate on every LinkedIn
deploy — dramatically more fragile, with no stability contract at all.

### Finding 2 — the TLS fingerprint is the real gate

The first implementation used a normal HTTP client with correct cookies and browser-like headers.
It worked, then the session was **invalidated globally** — logging the account out of the real
browser too — after a handful of requests.

The cause wasn't the cookies or the headers or the request rate. Anti-bot systems fingerprint the
**TLS handshake itself** (cipher order, extensions, HTTP/2 SETTINGS) via JA3 hashing, before a
single HTTP header is parsed. A valid session cookie arriving over an automation-shaped handshake
is, to LinkedIn, indistinguishable from a stolen session — and the correct response to a stolen
session is to kill it everywhere.

Measured against `tls.browserleaks.com`:

| Client | JA3 hash | Outcome |
| --- | --- | --- |
| `curl` | `4ea056e6…` | flagged → session invalidated |
| Node `fetch` / undici | `1a28e690…` | flagged → session invalidated |
| **`curl_cffi` (`impersonate="chrome"`)** | `51ed4e88…` | real Chrome fingerprint |

This is why the service is written in Python: `curl_cffi` is the practical way to present a
genuine browser TLS/HTTP2 fingerprint. It is the single most load-bearing line in the codebase
(`app/linkedin_client.py`), and no amount of header tuning or slower pacing substitutes for it.

### Finding 3 — the two cookie-quoting details that decide 200 vs. 302

LinkedIn stores `JSESSIONID` wrapped in literal double quotes, and the two places it's used need
*different* quoting. Verified by testing each combination:

| Cookie `JSESSIONID` | `csrf-token` header | Result |
| --- | --- | --- |
| `"ajax:123"` (quoted) | `ajax:123` (unquoted) | **200 OK** |
| `"ajax:123"` (quoted) | `"ajax:123"` (quoted) | 302 → login |
| `ajax:123` (unquoted) | `ajax:123` (unquoted) | 302 → login |

An invalid session is answered with a **302 redirect to the login page**, never a clean 401 — so
the client disables redirect-following and treats any 3xx as an auth failure. Without that you
follow the redirect and try to parse an HTML login page as JSON.

---

## Architecture

A naive implementation calls LinkedIn synchronously on every request. That burns rate budget on
repeat lookups, makes client latency a function of LinkedIn's mood, and loses everything the
moment the schema shifts. This is built as a pipeline that separates fetching (expensive, risky,
rate-limited) from serving (cheap, instant):

```
Client → API ──► Result Cache (hit) ──────────────────────► response
             └─► (miss) Job Queue → Worker → Session Manager → LinkedIn
                                                  │      (pacing + circuit breaker)
                                                  ▼
                                    Raw Payload Store (immutable)
                                                  │
                                                  ▼
                                    Parser (versioned) → Result Cache
```

| Component | File | Why it exists |
| --- | --- | --- |
| API gateway | `app/main.py` | Cache-first. On a miss, enqueues and long-polls briefly so the call still looks synchronous; falls back to `202 + jobId` rather than hanging. |
| Result cache | `app/stores/` | Repeat lookups cost zero LinkedIn requests — reduces detection risk as much as latency. |
| Job queue + worker | `app/worker.py` | One job at a time against one session. Decouples client load from LinkedIn call rate. |
| Session manager | `app/session_manager.py` | Pacing with jitter + **circuit breaker**: after repeated auth failures it stops entirely rather than pushing a flagged session toward a hard account restriction. |
| LinkedIn client | `app/linkedin_client.py` | TLS impersonation, exact cookie/csrf quoting, redirect-as-auth-failure. |
| Raw payload store | `app/stores/` | Every raw response persisted **before** parsing. |
| Parser | `app/profile_parser.py` | Pure `raw → profile`, versioned. Filters voyager's flat `included[]` entity list by `$type`. |

**Why storing raw payloads matters.** `voyager` is an internal API with no stability contract. When
its shape changes and the parser breaks, you fix the parser and replay it against already-stored
payloads (`POST /api/profile/{id}/reparse`) — recovering every previously-fetched profile without
spending a single additional LinkedIn request. Given that requests are the scarce, risky resource
here, that separation is the most valuable property in the design.

---

## Setup

### 1. Capture a LinkedIn session

1. Log into linkedin.com in a browser.
2. DevTools → Application → Cookies → `https://www.linkedin.com`.
3. Copy `li_at` and `JSESSIONID`.

### 2. Configure

```bash
cp .env.example .env
```

```
LI_AT_COOKIE=<li_at value>
LI_JSESSIONID=ajax:...           # with or without quotes; normalized internally
IMPERSONATE=chrome
```

`.env` is gitignored. No credentials are committed.

### 3. Install and run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Interactive API docs at `/docs` (FastAPI/OpenAPI, generated).

### 4. Deploy

Any host that runs a Python process (Render, Railway, Fly.io). Set `LI_AT_COOKIE`,
`LI_JSESSIONID`, and `IMPERSONATE` as platform secrets.

> **Note on persistence:** the JSON store writes to `DATA_DIR` on local disk. On hosts with
> ephemeral filesystems (most free tiers) that directory is wiped on redeploy — the cache
> degrades gracefully, but the raw-payload history that makes `/reparse` useful does not
> survive. Attach a persistent volume, or point the store at a managed database, if that
> history matters.

---

## Development workflow

Every LinkedIn request risks the session, and a dead session costs a manual browser re-login. So
development is **fixture-first**: spend one request, then iterate offline.

```bash
# Spend exactly ONE LinkedIn request; save the raw payload to fixtures/
python3 -m scripts.capture_fixture https://www.linkedin.com/in/some-profile

# Iterate on the parser against that fixture — zero requests, zero risk
python3 -m scripts.replay_fixture

# Offline tests (synthetic payload, no network)
python3 -m tests.test_smoke
```

`replay_fixture` prints a coverage summary of which sections populated, which is how you catch
LinkedIn having moved a section to a different entity type or a separate endpoint.

---

## API

### `GET /api/profile?url=<linkedin-profile-url>`

| Case | Response |
| --- | --- |
| Cache hit | `200`, `"source": "cache"`, plus `cachedAt` / `expiresAt` |
| Fetched within long-poll window | `200`, `"source": "live"` |
| Still running | `202` `{ "jobId", "status", "statusUrl" }` — poll `statusUrl` |
| Fetch failed | `502` `{ "error", "jobId" }` |
| Bad / non-LinkedIn URL | `400` |

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
  "profileImages": [{ "url": "https://media.licdn.com/...", "width": 400, "height": 400 }],
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
  "languages": [{ "name": "English", "proficiency": "NATIVE_OR_BILINGUAL" }],
  "fetchedAt": "2026-08-29T12:00:00+00:00",
  "source": "live"
}
```

### Other endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness |
| `GET /api/jobs/{id}` | Poll a job: `queued` / `processing` / `completed` / `failed` |
| `POST /api/profile/{id}/reparse` | Re-run the parser on the stored raw payload — no LinkedIn request |
| `GET /api/session/health` | Session state, consecutive failures, last error |
| `POST /api/session/reset` | Clear the circuit breaker after refreshing cookies |

---

## Known limitations

- **This violates LinkedIn's Terms of Service.** Automated access to non-public endpoints is
  against LinkedIn's User Agreement. The backing account risks being challenged, rate-limited, or
  restricted. This is a demonstration of technique, not a production-safe integration.
- **Sessions die unpredictably.** `li_at` is nominally long-lived (~1 year), but is invalidated
  early by password changes, "sign out of all devices," or anomaly detection. TLS impersonation
  substantially reduces that risk but does not eliminate it. There is no way to refresh without a
  browser login, so recovery is manual: capture new cookies, restart, `POST /api/session/reset`.
- **Single session, no pool.** Once the circuit breaker opens the service is down until someone
  refreshes the cookie. `session-health` is keyed for a future pool, but only one is wired today.
- **Undocumented, unstable upstream schema.** Field names and `$type` values have changed between
  LinkedIn releases and will again. The raw-payload store plus `/reparse` limits the blast radius;
  it doesn't prevent the breakage.
- **Partial data by design.** Fields the target profile restricts (e.g. connections-only) return
  `null`/empty rather than erroring. `profileView` is a single call — contact info and some
  paginated sections live behind separate endpoints that aren't fetched.
- **JSON-file store, not a database.** Fine for one process at moderate volume; unsafe for
  concurrent writers, and no querying beyond key lookup. Store modules sit behind narrow
  interfaces so swapping in SQLite/Postgres/Redis wouldn't touch pipeline logic.
- **No auth on this API.** Anyone who can reach the deployed URL can spend your LinkedIn session's
  rate budget. An API key and per-caller rate limit would be the first thing to add before
  exposing this anywhere real.
- **Long-poll, not push.** Callers past the long-poll window must poll `/api/jobs/{id}`; there's
  no webhook or SSE completion notification.

## Considered and rejected

- **RSC / flight-protocol reverse engineering** — what the browser actually uses today, but
  requires tracking build-hash action IDs that rotate every deploy and parsing React's internal
  stream format. Voyager works and is far more stable. (Finding 1.)
- **Residential/mobile proxy rotation** — standard for anonymous scraping, counterproductive here:
  bouncing *one authenticated session* across rotating IPs and geographies is itself a strong
  account-compromise signal. A single stable egress IP is safer for session-based access.
- **Username/password login flow** — performing the login handshake server-side trips security
  challenges (CAPTCHA/2FA) far more readily than reusing an existing session, and would mean
  storing full credentials rather than a revocable token.
- **Public-page JSON-LD only** — no session and no account risk, but returns a thin subset
  (roughly name/headline/partial experience), missing the skills, certifications, languages, and
  full about text this API is required to return. Viable as a future degraded fallback when the
  circuit breaker is open; not viable as the primary path.
