# Session notes — LinkedIn Profile API

Working notes from building this, kept so the work can be picked up on another machine without
re-deriving the reasoning. The README is the polished write-up; this is the log of how it got
there, including the wrong turns, because those explain why the code looks the way it does.

**No credentials in this file.** Where they live is noted; the values are not.

---

## 1. The task

Tross engineering challenge. Build and publicly host an HTTPS API that accepts a LinkedIn
profile URL and returns the profile as structured JSON: name, headline, location, about,
experience, education, skills, certifications, languages, profile images.

A follow-up email narrowed it: *"a purely reverse-engineered solution that directly hits LinkedIn
endpoints and does not use a browser."* No Puppeteer, Playwright, Selenium.

Deadline: 31 August. Submission: https://tally.so/r/KYK6qg

---

## 2. Current state

**Repo:** https://github.com/akshaytiwari12/linkedin_profile_api
**Deployed:** https://linkedin-profile-api-tmc0.onrender.com

| Endpoint | Purpose |
| --- | --- |
| `/docs` | Swagger UI — assets vendored, no CDN dependency |
| `/redoc` | Alternative reference |
| `/status` | Human-readable session health + recent requests |
| `/api/logs` | Same data as JSON |
| `/api/profile?url=…` | The main endpoint |
| `/api/jobs/{id}` | Poll an async fetch |
| `/api/profile/{slug}/reparse` | Re-parse stored HTML, no LinkedIn request |
| `/api/session/health`, `/api/session/reset` | Circuit breaker |
| `/health` | Liveness |

**Works:** parser validated against five real profiles; two offline test suites pass; deployment
live; docs complete.

**Does not work:** live fetching from the deployed instance. Two separate causes, both
documented below — the datacenter IP, and (later) the development account hitting LinkedIn's
rate limits.

**Outstanding:** the GitHub repo is still **private** and must be made public before submitting.

---

## 3. How the solution was found

### 3.1 The documented endpoints are dead

Nearly every public write-up points at voyager's REST API. Tested directly:

| Endpoint | Result |
| --- | --- |
| `/voyager/api/me` | **200** — voyager itself is alive |
| `/voyager/api/identity/profiles/{id}/profileView` | **410 Gone** |
| `/voyager/api/identity/profiles/{id}` | 302 |
| `/voyager/api/identity/dash/profiles` (slug or URN) | 302 |
| public profile page, no cookies | **999** authwall |

`profileView` — the endpoint every tutorial uses — is explicitly tombstoned. Since `/me` returns
200 with the same credentials, these are endpoint deaths rather than auth failures.

### 3.2 The browser no longer reveals the API

DevTools shows **no** voyager calls on linkedin.com. The desktop site loads profiles through
React Server Components (`POST /flagship-web/rsc-action/actions/component`). Voyager did not
disappear — it moved *behind* LinkedIn's own server, where DevTools cannot see it, and the parts
still reachable from outside no longer include profiles.

**The surface that works is `mwlite`** — LinkedIn's mobile web client, which **server-renders the
whole profile into the HTML**. One authenticated `GET https://www.linkedin.com/in/{slug}/` with a
mobile user agent returns everything. This was found from cURLs captured in mobile emulation;
it does not appear in desktop traffic.

Consequence: the parser reads markup, not JSON. Not a preference — the JSON surfaces are gone.

### 3.3 TLS fingerprinting is the real gate

First implementation (Node/TypeScript) had correct cookies and browser-like headers. It worked,
then the session was **invalidated globally**, logging the account out of the real browser too.

Cause: anti-bot systems fingerprint the **TLS handshake** (cipher order, extensions, HTTP/2
SETTINGS) via JA3, before any HTTP header is read. A valid cookie over an automation-shaped
handshake looks like a stolen session, and the response to a stolen session is to kill it.

Measured against `tls.browserleaks.com`:

| Client | JA3 | Outcome |
| --- | --- | --- |
| `curl` | `4ea056e6…` | flagged |
| Node `fetch`/undici | `1a28e690…` | flagged |
| `curl_cffi` (`chrome131_android`) | `51ed4e88…` | real Chrome |

**This is why the project is Python.** Node has no practical TLS-impersonation library;
`curl_cffi` does it natively. The whole Node implementation was discarded for this one reason
(commit `aa3d96a`).

### 3.4 Cookies split into durable and volatile

A request that worked would redirect-loop thirty minutes later with nothing changed.

| Class | Cookies | Lifetime |
| --- | --- | --- |
| Durable | `li_at`, `JSESSIONID`, `bcookie`, `liap` | long — these go in env vars |
| Volatile | `__cf_bm`, `lidc` | `__cf_bm` dies after 30 min idle |

`__cf_bm` is Cloudflare's bot token: encrypted, unforgeable. **Replaying a stale one is worse
than omitting it** — the server tries to reissue while the client keeps presenting the expired
value, and they bounce until the redirect limit trips.

Fix: `app/session_jar.py` seeds only durable cookies; the client holds one long-lived session
(`app/linkedin_client.py`) and lets LinkedIn issue the volatile ones via `Set-Cookie`. Verified
by `scripts/check_deploy_viability.py`. **This is why `LI_COOKIE_JAR` should be left empty** —
fewer cookies pasted means a longer-lasting deployment.

Two quoting details, each producing a 302 if wrong:
- the `JSESSIONID` **cookie** keeps its double quotes; the `csrf-token` **header** must not
- an invalid session gets a **302 to login**, never a 401 — so redirects are treated as auth
  failures rather than followed into an HTML page

---

## 4. Parser: what the markup forces

Selectors anchor on LinkedIn's **semantic component classes**, never layout/utility classes:

| Field | Anchor |
| --- | --- |
| headline | top-card child `div.body-small.text-color-text` |
| location | top-card child `div.body-small.…low-emphasis` ending in a connection count |
| current company | `member-current-company` |
| experience / education | `profile-entity-lockup`, bucketed by nearest preceding heading |
| skills | `skill-item` |
| certifications | list items under the `Certifications` heading |

Non-obvious things:

- **Dates split across sibling spans** (`"Jan 2024 -"` / `"Present"`) — ranges must be matched
  against the joined text of a lockup, never a single line.
- **A lockup's heading is the COMPANY, not the job title.** LinkedIn groups roles by employer;
  each role is a nested `body-small-bold` span. Reading the heading as the title inverts both
  fields on every entry, and collapsing the lockup to one entry drops every role after the first.
- **Duration lines** (`2 yrs 8 mos`) and `…more` / `See less` affordances must be filtered before
  fields are assigned, or they contaminate company and location.
- **The top card's rows are container divs**, so a leaf-node walk skips the location row entirely
  and picks up the school/company row above it.

### The lesson worth carrying forward

Three real bugs survived five rounds of structural validation — counts, section reconciliation,
DOM inspection — because **field counts look identical whether or not the values are correct**.
They were only found by printing one real profile's contents and reading it. Validate values, not
counts.

---

## 5. Architecture

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

| File | Role |
| --- | --- |
| `app/main.py` | FastAPI app, routes, request-logging middleware |
| `app/linkedin_client.py` | TLS impersonation, long-lived session, header/cookie format |
| `app/session_jar.py` | Durable/volatile cookie split |
| `app/session_manager.py` | Pacing with jitter + circuit breaker |
| `app/worker.py` | Single worker draining the job queue |
| `app/html_parser.py` | `html → profile`, versioned |
| `app/stores/` | JSON-file cache, raw payloads, jobs, session health |
| `app/models.py` | Pydantic response models (also what populates `/docs`) |
| `app/request_log.py`, `app/status_page.py` | Observability |

**Why raw HTML is stored before parsing:** LinkedIn requests are the scarce, risky resource. When
the markup changes and the parser breaks, you fix the parser and replay it against stored pages
(`POST /api/profile/{slug}/reparse`) — recovering every previously-fetched profile without
spending another request. This is the most valuable property in the design.

**Pacing is deliberate:** ~1 request/minute with jitter, matching published guidance of 1–2/min
and ~80–100/day per account. A burst queues rather than running in parallel.

---

## 6. Deployment and the IP problem

### What was measured

Deployed to Render (Singapore). The first live profile request failed — and the cookie, verified
working from a home connection fifteen minutes earlier, was **dead everywhere afterwards,
including locally**. The deployed request did not fail to authenticate; it caused LinkedIn to
revoke the session globally.

Published survival rates by egress type:

| Egress | Survives |
| --- | --- |
| Datacenter (AWS/GCP/PaaS) | 10–20% — consistent with what was measured |
| Residential proxy | ~50% |
| Mobile carrier | ~85% |
| Own residential connection | the only configuration proven here |

**Changing cloud host cannot fix this.** Every provider's IPs register to hosting ASNs, which is
what LinkedIn checks. Mumbai vs Singapore only affects the secondary geography signal.

### Proxy options — all gated

| Provider | Gate |
| --- | --- |
| Decodo (formerly Smartproxy) | credit card |
| Bright Data | KYC + intro video call (API key confirmed; token also lacked zone-create permission) |
| GoProxy / GloryCloud | support ticket to activate |
| Oxylabs | business verification |

Not coincidence — residential IPs are real people's connections, so access is gated to keep abuse
traceable. There is no ungated residential proxy worth trusting with a session cookie.

### What works

Run locally and put a tunnel in front of it. Requests leave from the residential connection the
cookie was created on:

```bash
./cloudflared tunnel --url http://localhost:8000   # prints an https://*.trycloudflare.com URL
```

No account needed. `cloudflared` is already downloaded in the project root (gitignored).

---

## 7. Account state — read before testing again

The development account was invalidated **six times** in one day. By the end, the web surface
began redirecting to `/hp` (the logged-out homepage) even while `/voyager/api/me` still returned
200 — the API tolerated the token while the browsing flow refused to authenticate it.

A 3–4 hour cool-off did **not** clear it, which suggests the restriction is measured in days.

**Practical guidance:**
- Expect a fresh cookie to be needed before any live test
- Do not test repeatedly; each failure reinforces the flag
- The next escalation above session invalidation is account restriction
- Consider a different account for further development

---

## 8. Credentials — where, not what

| Secret | Location | Notes |
| --- | --- | --- |
| `LI_AT_COOKIE` | `.env` (gitignored), and Render env vars | expires; from DevTools → Application → Cookies |
| `LI_JSESSIONID` | same | changes on re-login |
| `LI_COOKIE_JAR` | optional — **leave empty** | contains `__cf_bm`, which goes stale in 30 min |
| `LINKEDIN_PROXY` | unset | for a sticky residential proxy, if one is ever obtained |
| GitHub PAT | not stored in repo | used via git credential cache |

`.env`, `fixtures/`, `data/` and `cloudflared` are all gitignored. Nothing sensitive is tracked —
verified before each commit.

`fixtures/` holds captured profile pages of **real people** and must never be committed.

---

## 9. Useful commands

```bash
# offline — no LinkedIn requests
python3.11 -m tests.test_html_parser
python3.11 -m tests.test_smoke
python3.11 -m scripts.replay_html fixtures/<slug>.mwlite.html      # parse a saved page
python3.11 -m scripts.replay_html fixtures/<slug>.mwlite.html --show   # full JSON
python3.11 -m scripts.seed_from_fixture                            # load a fixture into the store

# one LinkedIn request each — use sparingly
python3.11 -m scripts.check_session                 # is the session alive? (own account only)
python3.11 -m scripts.capture_profile <slug>        # save a profile page to fixtures/
python3.11 -m scripts.check_deploy_viability <slug> # can it run on durable cookies alone?
python3.11 -m scripts.inspect_markup fixtures/<slug>.mwlite.html   # top-card DOM structure

# run it
uvicorn app.main:app --port 8000
```

**Development is fixture-first**: spend one request to capture a page, then iterate offline
against it. Every live request risks the session, and a dead session costs a browser re-login.

---

## 10. What is left

1. **Make the GitHub repo public** — required by the brief, still private
2. **Submit** at https://tally.so/r/KYK6qg with the repo and deployed URLs
3. Optional: run the tunnel for a live demo, if the account has recovered

### Suggested framing for the submission

The service works and is validated against five real profiles. The deployed instance serves the
API and its documentation, but live fetches from it require a residential egress IP — a cloud IP
causes LinkedIn to revoke the session on first use, which was measured and is documented. The
development account also hit LinkedIn's rate limits during testing. Both are documented in the
README as known limitations rather than left to be discovered.

---

## 11. Things deliberately not done

- **RSC / flight-protocol reverse engineering** — what the desktop site uses, but requires
  tracking build-hash action IDs that rotate every deploy and parsing React's internal stream
  format. mwlite returns the same data to one plain request.
- **Rotating proxy pools** — standard for anonymous scraping, counterproductive here: bouncing
  one authenticated session across IPs is itself an account-compromise signal.
- **Username/password login flow** — trips security challenges far more readily than reusing a
  session, and would mean storing full credentials rather than a revocable token.
- **Public-page JSON-LD** — no session and no account risk, but unauthenticated profile requests
  return a `999` authwall, and the data would be a thin subset anyway.
- **Company/organization pages** — the brief asks for profile-page data; company pages are a
  different URL type and surface.
