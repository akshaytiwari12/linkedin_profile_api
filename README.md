# LinkedIn Profile API

An HTTP API that accepts a LinkedIn profile URL and returns the profile as structured JSON.
It reaches LinkedIn directly over HTTP — **no browser, no headless Chrome, no automation
framework** — using a logged-in session cookie and a TLS fingerprint that matches a real browser.

```bash
curl "http://localhost:8000/api/profile?url=https://www.linkedin.com/in/some-profile"
```

---

## Approach

LinkedIn has no public API for reading arbitrary profile data, so the endpoint has to be found
rather than looked up. The interesting part of this problem turned out not to be finding *an*
endpoint — it was that most of the documented ones are dead, and that staying authenticated is
harder than getting authenticated. Four findings shaped the final design, each established by
testing against the live API.

### Finding 1 — the documented endpoints are gone

Nearly every public write-up on this subject points at `voyager`'s REST API. Tested directly:

| Endpoint | Result |
| --- | --- |
| `GET /voyager/api/me` | **200** — voyager itself is alive |
| `GET /voyager/api/identity/profiles/{id}/profileView` | **410 Gone** |
| `GET /voyager/api/identity/profiles/{id}` | 302 → login |
| `GET /voyager/api/identity/dash/profiles?q=memberIdentity` | 302 → login |
| `GET /voyager/api/identity/dash/profiles/{urn}` | 302 → login |
| public profile page, unauthenticated | **999** authwall |

`profileView` — the endpoint almost every tutorial uses — is explicitly tombstoned. The rest of
the identity surface answers with a catch-all redirect. Since `/me` still returns 200 with the
same credentials, these are endpoint deaths, not auth failures.

### Finding 2 — the browser no longer reveals the API

Watching linkedin.com in DevTools shows **no** `voyager` calls at all. The desktop site loads
profiles through React Server Components (`POST /flagship-web/rsc-action/actions/component`).
It is tempting to conclude voyager is gone and that the RSC protocol must be reverse-engineered.

That conclusion is wrong, but so is the opposite one. Under RSC the flow became:

```
browser → rsc-action → LinkedIn's server → voyager (internal) → rendered payload → browser
```

Voyager didn't disappear; it moved *behind* LinkedIn's own server, where DevTools cannot see it —
and the parts of it still reachable from outside no longer include profiles.

The surface that does still work is **mwlite**, LinkedIn's lightweight mobile web client. Unlike
the desktop app, mwlite **server-renders the entire profile into the HTML**. That has a useful
consequence: one plain HTTP request returns the whole profile, with no client-side fetching to
replicate. It also explains why there is no profile GraphQL query to call — mwlite's
`runQuery` endpoint exists (and works) but the profile never travels through it.

So the fetch is a single authenticated `GET https://www.linkedin.com/in/{identifier}/` with a
mobile user agent, and the parser reads markup.

### Finding 3 — the TLS fingerprint is the real gate

The first implementation used a normal HTTP client with correct cookies and browser-like headers.
It worked — and then the session was **invalidated globally**, logging the account out of the
real browser too, after a handful of requests.

The cause was not the cookies, the headers, or the request rate. Anti-bot systems fingerprint the
**TLS handshake itself** (cipher order, extensions, HTTP/2 SETTINGS) via JA3 hashing, before a
single HTTP header is parsed. A valid session cookie arriving over an automation-shaped handshake
is indistinguishable from a stolen session, and the correct response to a stolen session is to
kill it everywhere.

Measured against `tls.browserleaks.com`:

| Client | JA3 hash | Outcome |
| --- | --- | --- |
| `curl` | `4ea056e6…` | flagged → session invalidated |
| Node `fetch` / undici | `1a28e690…` | flagged → session invalidated |
| **`curl_cffi` (`chrome131_android`)** | `51ed4e88…` | genuine Chrome fingerprint |

This is why the service is written in Python: `curl_cffi` is the practical way to present a real
browser TLS/HTTP2 fingerprint. It is the single most load-bearing line in the codebase
(`app/linkedin_client.py`), and no amount of header tuning substitutes for it.

### Finding 4 — cookies split into durable and volatile

A request that worked would start redirect-looping thirty minutes later with nothing changed.
The jar has two classes of cookie and conflating them is what causes it:

| Class | Cookies | Lifetime |
| --- | --- | --- |
| **Durable** | `li_at`, `JSESSIONID`, `bcookie`, `liap` | long-lived — these belong in `.env` |
| **Volatile** | `__cf_bm`, `lidc` | `__cf_bm` expires after **30 minutes of inactivity** |

`__cf_bm` is Cloudflare's bot-management token: encrypted, decryptable only by Cloudflare, and
therefore impossible to forge. Replaying a stale one is *worse* than omitting it — the server
tries to re-issue while the client keeps presenting the expired value, and the two bounce until
the redirect limit trips. `app/session_jar.py` seeds only the durable cookies and lets the
session collect the volatile ones from `Set-Cookie`.

Two smaller details, both of which produce a 302 if wrong:

- the `JSESSIONID` **cookie** keeps its surrounding double quotes; the `csrf-token` **header**
  must not have them
- an invalid session gets a **302 to the login page**, never a clean 401 — so redirects are
  treated as auth failures rather than followed into an HTML login page

---

## Architecture

A naive implementation calls LinkedIn synchronously on every request. That burns a scarce,
risky resource on repeat lookups, makes client latency a function of LinkedIn's mood, and loses
everything already fetched the moment the markup shifts. This is built as a pipeline that
separates fetching (expensive, rate-limited, account-risking) from serving (cheap, instant):

```
Client → API ──► Result Cache (hit) ──────────────────────► response
             └─► (miss) Job Queue → Worker → Session Manager → LinkedIn
                                                  │      (pacing + circuit breaker)
                                                  ▼
                                       Raw HTML Store (immutable)
                                                  │
                                                  ▼
                                    Parser (versioned) → Result Cache
```

| Component | File | Why it exists |
| --- | --- | --- |
| API gateway | `app/main.py` | Cache-first. On a miss it enqueues and briefly long-polls so the call still looks synchronous, then falls back to `202 + jobId` rather than hanging. |
| Result cache | `app/stores/` | Repeat lookups cost zero LinkedIn requests — that reduces detection risk as much as latency. |
| Job queue + worker | `app/worker.py` | One job at a time against one session; decouples client load from LinkedIn call rate. |
| Session manager | `app/session_manager.py` | Pacing with jitter, plus a **circuit breaker** that stops entirely after repeated auth failures rather than pushing a flagged session toward a hard account restriction. |
| LinkedIn client | `app/linkedin_client.py` | TLS impersonation, cookie/csrf quoting, redirect-as-auth-failure. |
| Cookie jar | `app/session_jar.py` | Durable/volatile split (Finding 4). |
| Raw HTML store | `app/stores/` | Every fetched page persisted **before** parsing. |
| Parser | `app/html_parser.py` | Pure `html → profile`, versioned. |

**Why the raw store matters.** The markup is an internal implementation detail with no stability
contract. When it changes and the parser breaks, you fix the parser and replay it against pages
already on disk (`POST /api/profile/{id}/reparse`) — recovering every previously-fetched profile
without spending another LinkedIn request. Given that requests are the scarce and risky resource
here, that separation is the most valuable property in the design.

### Parser strategy

Selectors anchor on LinkedIn's **semantic component classes**, never on layout or utility
classes, and sections are located by their heading text rather than by position:

| Field | Anchor |
| --- | --- |
| headline | span whose parent is `body-small text-color-text` |
| location | span whose parent is `body-small text-color-text-low-emphasis` |
| current company | `member-current-company` |
| experience / education | `profile-entity-lockup`, bucketed by nearest preceding heading |
| skills | `skill-item` |
| certifications | list items under the `Certifications` heading |

Two details the markup forces:

- **Dates are split across sibling spans** (`"Jan 2024 -"` / `"Present"`), so ranges are matched
  against the joined text of a lockup rather than any single line.
- **Duration lines** (`2 yrs 8 mos`) and collapsible affordances (`…more`, `See less`) are
  filtered before fields are assigned, or they contaminate company and location.

An earlier version picked these fields by text length and position instead. It mis-assigned
silently and differently per profile — one sample returned its About text as the headline,
another returned its headline as the location, and a profile with no location returned its
company in that field. All three passed a casual eyeball. `tests/test_html_parser.py` pins both
observed top-card orderings so that class of bug cannot return.

---

## Setup

### 1. Capture a LinkedIn session

1. Log into linkedin.com in a browser.
2. DevTools → Network → any request → **Copy as cURL**.
3. Take the `cookie:` header value, plus `li_at` and `JSESSIONID` from it.

### 2. Configure

```bash
cp .env.example .env
```

```
LI_AT_COOKIE=<li_at value>
LI_JSESSIONID=ajax:...            # with or without quotes; normalized internally
LI_COOKIE_JAR=<full cookie header>  # optional but recommended
IMPERSONATE=chrome
```

`.env` is gitignored. No credentials are committed.

### 3. Install and run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Interactive OpenAPI docs at `/docs`.

### 4. Deploy

Any host that runs a Python process (`Procfile`, `render.yaml`, and `runtime.txt` are included).
Set the cookie values as platform secrets — see the deployment caveat under Known Limitations,
which is significant.

---

## Development workflow

Every LinkedIn request risks the session, and a dead session costs a manual browser re-login. So
development is **fixture-first**: spend one request, then iterate offline.

```bash
# Offline tests — synthetic markup, no network
python3 -m tests.test_html_parser
python3 -m tests.test_smoke

# Parse a captured page and report field coverage
python3 -m scripts.replay_html fixtures/<slug>.mwlite.html

# Load a fixture into the store so the API can be exercised with no network at all
python3 -m scripts.seed_from_fixture

# Is the configured session still alive? (one request, own account only)
python3 -m scripts.check_session
```

`fixtures/` is gitignored — captured pages contain real people's personal data and must not
reach a public repository.

---

## API

### `GET /api/profile?url=<linkedin-profile-url>`

| Case | Response |
| --- | --- |
| Cache hit | `200`, `"source": "cache"`, plus `cachedAt` / `expiresAt` |
| Fetched within long-poll window | `200`, `"source": "live"` |
| Still running | `202` `{ "jobId", "status", "statusUrl" }` — poll `statusUrl` |
| Fetch failed | `502` `{ "error", "jobId" }` |
| Bad or non-LinkedIn URL | `400` |

```json
{
  "publicIdentifier": "some-profile",
  "profileUrl": "https://www.linkedin.com/in/some-profile/",
  "firstName": "Jane",
  "lastName": "Doe",
  "fullName": "Jane Doe",
  "headline": "Principal Engineer — Platform & Reliability",
  "location": "Bengaluru, Karnataka, India",
  "currentCompany": "Example Systems",
  "about": "...",
  "profileImages": [{ "url": "https://media.licdn.com/...", "width": null, "height": null }],
  "experience": [
    {
      "title": "Principal Engineer",
      "companyName": "Example Systems",
      "location": "Bengaluru, Karnataka, India",
      "description": "...",
      "startDate": { "month": 1, "year": 2024 },
      "endDate": null,
      "isCurrent": true
    }
  ],
  "education": [
    {
      "schoolName": "Example University",
      "degreeName": "BBA",
      "fieldOfStudy": "Information Technology",
      "startYear": 2008,
      "endYear": 2010,
      "description": null
    }
  ],
  "skills": [{ "name": "Distributed Systems", "endorsementCount": null }],
  "certifications": [{ "name": "AWS Certified Developer", "authority": null, "startDate": null, "endDate": null }],
  "languages": [{ "name": "English", "proficiency": null }],
  "fetchedAt": "2026-08-30T19:20:05+00:00",
  "source": "live"
}
```

Absent sections return `null` or `[]` rather than an error — a profile with no About or no
Languages section is normal, and the API reports that honestly rather than guessing.

### Other endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness |
| `GET /api/jobs/{id}` | Poll a job: `queued` / `processing` / `completed` / `failed` |
| `POST /api/profile/{id}/reparse` | Re-run the parser on the stored page — no LinkedIn request |
| `GET /api/session/health` | Session state, consecutive failures, last error |
| `POST /api/session/reset` | Clear the circuit breaker after refreshing cookies |

---

## Validation

Verified end to end against five live profiles of deliberately different shape and size:

| | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| experience | 14 | 7 | 4 | 2 | 11 |
| education | 3 | 3 | 1 | 1 | 2 |
| skills | 37 | 9 | 31 | 9 | 30 |
| certifications | 6 | 8 | 0 | 1 | 6 |
| languages | 3 | 0 | 0 | 0 | 2 |
| about | yes | — | — | yes | yes |

Every empty value was confirmed against the markup rather than assumed — a section absent from
the page is reported as `[]`/`null` rather than guessed at. Element counts reconcile exactly
(e.g. profile C: 5 lockups = 4 experience + 1 education, 31 `skill-item` = 31 skills, 0
`sub-list-item` = 0 certifications).

Three bugs were found only by printing a real profile's *contents* rather than field counts,
which is worth recording because counts look identical whether or not values are correct:

- **Title and company were inverted on every experience entry.** LinkedIn groups positions by
  employer, so a lockup's `list-item-heading` is the *company* and each role is a nested
  `body-small-bold` span. Reading the heading as the job title inverts both fields.
- **Roles after the first were silently dropped.** The same grouping means anyone promoted
  within a company had their earlier positions discarded; one test profile returned 1 entry
  where the profile listed 5.
- **Member location was never real.** See Known Limitations.

## Known limitations

- **This violates LinkedIn's Terms of Service.** Automated access to non-public endpoints is
  against LinkedIn's User Agreement. The backing account risks being challenged, rate-limited or
  restricted. This is a demonstration of technique, not a production-safe integration.
- **Deployment fights an IP constraint.** LinkedIn checks that session cookie, client
  fingerprint and IP reputation are mutually consistent. A cookie captured at home and then used
  from a cloud host is an IP that has never logged into that account, which burns sessions
  quickly. A deployed instance realistically needs `LINKEDIN_PROXY` pointed at a **sticky**
  residential proxy in the login's region — a rotating pool is *worse* than none, since changing
  IP mid-session invalidates it outright. Without one, expect the live path to degrade to auth
  failures while cached results keep serving. Running locally, from the machine the cookie was
  created on, avoids this entirely.
- **Sessions die unpredictably.** Roughly 1–2 requests/minute and ~80–100/day per account is the
  safe envelope; the pacing defaults target the low end. TLS impersonation substantially reduces
  invalidation risk but does not eliminate it. Recovery is manual: capture new cookies, restart,
  `POST /api/session/reset`.
- **HTML parsing is inherently more fragile than a JSON contract.** This is a deliberate
  trade-off, not a preference — LinkedIn retired every JSON profile surface reachable from
  outside (Finding 1). Anchoring on semantic component classes and heading text mitigates it, and
  the raw-page store plus `/reparse` limits the blast radius, but a markup change will break
  fields and the recovery is a parser fix.
- **Member location is not available.** The mwlite top card has a slot where a location would
  sit, but across every profile tested it contains the member's *school* rather than a location,
  and no location string appears anywhere else in the page — not in the markup, not in meta tags,
  not in the title. `location` is therefore `null`. An earlier version returned that slot's
  contents and so reported school and company names as locations: plausible-looking values that
  were simply wrong, which is worse than reporting nothing. Per-role locations *are* available
  and are returned on `experience[].location`.
- **Long descriptions are truncated by the source.** mwlite server-renders only the collapsed
  portion of a long text block, with the remainder behind a client-side expand this service does
  not perform. The trailing `…more` affordance is stripped, but the text it hides is not
  recoverable from a single request.
- **Certification issuer is unavailable.** mwlite renders the issuer inline with the
  certification name rather than as a separate element, so `authority` is always `null`. This is
  a property of the surface, confirmed across all test profiles.
- **Skill endorsement counts are unavailable** on mwlite, so `endorsementCount` is always `null`.
- **Partial data by design.** Fields a profile restricts to connections-only return `null`/`[]`.
- **Single session, no pool.** Once the circuit breaker opens the service is down until someone
  refreshes the cookie. `session-health` is keyed for a future pool; only one is wired today.
- **JSON-file store, not a database.** Fine for one process at moderate volume; unsafe for
  concurrent writers and no querying beyond key lookup. Store modules sit behind narrow
  interfaces so SQLite/Postgres/Redis could be swapped in without touching pipeline logic. Note
  that hosts with ephemeral filesystems wipe `DATA_DIR` on redeploy, which costs the raw-page
  history that makes `/reparse` useful.
- **No auth on this API.** Anyone who can reach the deployed URL can spend the LinkedIn
  session's rate budget. An API key and per-caller rate limit is the first thing to add before
  exposing it anywhere real.
- **Long-poll, not push.** Callers past the long-poll window must poll `/api/jobs/{id}`.
- **Profiles only.** The brief asks for profile-page data; company/organization pages are a
  different URL type and surface, and are not handled.

## Considered and rejected

- **RSC / flight-protocol reverse engineering** — what the desktop site actually uses, but it
  requires tracking build-hash action IDs that rotate on every deploy and parsing React's
  internal stream format. mwlite returns the same data to one plain request.
- **Residential proxy rotation** — standard for anonymous scraping, counterproductive here:
  bouncing *one authenticated session* across rotating IPs is itself a strong
  account-compromise signal. A single stable egress IP is safer for session-based access.
- **Username/password login flow** — performing the login handshake server-side trips security
  challenges far more readily than reusing an existing session, and would mean storing full
  credentials rather than a revocable token.
- **Public-page JSON-LD** — no session and no account risk, but unauthenticated profile requests
  are answered with a `999` authwall, and the data would be a thin subset in any case.
