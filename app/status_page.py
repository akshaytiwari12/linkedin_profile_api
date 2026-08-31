"""A human-readable status page.

`/api/logs` returns JSON, which is fine for tooling and unpleasant to read in a browser. The two
questions someone actually opens a status page to answer are "is the LinkedIn session still
usable" and "did anything hit this recently, and did it work" — so those are the two things this
puts at the top, in that order.

Rendered server-side with no external assets, so it works on any network and cannot break the
service if a CDN is unreachable.
"""

from __future__ import annotations

import html
from typing import Any

_STYLE = """
:root { color-scheme: light dark; }
body { font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 0; padding: 2rem 1.5rem; max-width: 60rem; margin-inline: auto; }
h1 { font-size: 1.35rem; margin: 0 0 .25rem; }
.sub { opacity: .65; margin: 0 0 2rem; font-size: .9rem; }
.card { border: 1px solid rgba(128,128,128,.28); border-radius: 10px;
        padding: 1rem 1.15rem; margin-bottom: 1.5rem; }
.card h2 { font-size: .78rem; text-transform: uppercase; letter-spacing: .06em;
           opacity: .6; margin: 0 0 .75rem; font-weight: 600; }
.state { font-size: 1.05rem; font-weight: 600; }
.ok { color: #15803d; } .bad { color: #b91c1c; } .warn { color: #b45309; }
@media (prefers-color-scheme: dark) {
  .ok { color: #4ade80; } .bad { color: #f87171; } .warn { color: #fbbf24; }
}
.detail { opacity: .7; font-size: .88rem; margin-top: .4rem; }
table { width: 100%; border-collapse: collapse; font-size: .87rem; }
th { text-align: left; font-weight: 600; opacity: .55; padding: .35rem .6rem .5rem 0;
     border-bottom: 1px solid rgba(128,128,128,.25); font-size: .78rem;
     text-transform: uppercase; letter-spacing: .04em; }
td { padding: .45rem .6rem .45rem 0; border-bottom: 1px solid rgba(128,128,128,.12);
     vertical-align: top; }
td.mono, th.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem; }
.pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .78rem;
        background: rgba(128,128,128,.15); white-space: nowrap; }
.pill.ok { background: rgba(34,197,94,.16); }
.pill.bad { background: rgba(239,68,68,.16); }
.pill.warn { background: rgba(245,158,11,.16); }
.empty { opacity: .6; font-style: italic; }
.counts { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.counts div { font-size: .87rem; }
.counts strong { display: block; font-size: 1.3rem; font-weight: 600; }
footer { opacity: .5; font-size: .8rem; margin-top: 2.5rem; }
a { color: inherit; }
"""


def _pill_class(outcome: str) -> str:
    if outcome.startswith("ok"):
        return "ok"
    if outcome in ("queued", "bad request"):
        return "warn"
    return "bad"


def render(session: dict[str, Any], summary: dict[str, Any], requests: list[dict[str, Any]]) -> str:
    flagged = session.get("state") == "flagged"

    if flagged:
        session_block = (
            '<div class="state bad">Session rejected by LinkedIn</div>'
            f'<div class="detail">{html.escape(str(session.get("lastError") or ""))}</div>'
            '<div class="detail">Refresh <code>LI_AT_COOKIE</code> in the environment, restart, '
            'then POST <code>/api/session/reset</code>.</div>'
        )
    else:
        last = session.get("lastRequestAt") or "no requests yet"
        session_block = (
            '<div class="state ok">Session healthy</div>'
            f'<div class="detail">Last LinkedIn request: {html.escape(str(last))}</div>'
        )

    by_outcome = summary.get("byOutcome") or {}
    counts = "".join(
        f"<div><strong>{v}</strong>{html.escape(k)}</div>" for k, v in sorted(by_outcome.items())
    ) or '<div class="empty">Nothing recorded yet.</div>'

    if requests:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{html.escape(str(r.get("at", ""))[11:19])}</td>'
            f'<td class="mono">{html.escape(str(r.get("path", "")))}</td>'
            f'<td class="mono">{html.escape(str(r.get("profile") or "—"))}</td>'
            f'<td><span class="pill {_pill_class(str(r.get("outcome", "")))}">'
            f'{html.escape(str(r.get("outcome", "")))}</span></td>'
            f'<td class="mono">{r.get("durationMs", 0)} ms</td>'
            "</tr>"
            for r in requests
        )
        table = (
            "<table><thead><tr><th class='mono'>Time (UTC)</th><th>Endpoint</th>"
            "<th>Profile</th><th>Outcome</th><th>Took</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        table = '<p class="empty">No requests recorded in this process yet.</p>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn Profile API — status</title>
<style>{_STYLE}</style></head>
<body>
  <h1>LinkedIn Profile API</h1>
  <p class="sub">Service status and recent activity ·
     <a href="/docs">API reference</a> · <a href="/api/logs">raw JSON</a></p>

  <div class="card">
    <h2>LinkedIn session</h2>
    {session_block}
  </div>

  <div class="card">
    <h2>Requests seen by this process</h2>
    <div class="counts">{counts}</div>
  </div>

  <div class="card">
    <h2>Recent requests</h2>
    {table}
  </div>

  <footer>
    Counts and history cover the current process only — a restart clears them, and on a host with
    an ephemeral filesystem so does a redeploy. The platform's own log stream retains the same
    entries for longer.
  </footer>
</body></html>"""
