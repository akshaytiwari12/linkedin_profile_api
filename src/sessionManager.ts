import { config } from "./config";
import { LinkedInAuthError, LinkedInBlockedError, SessionFlaggedError } from "./errors";
import { fetchProfileView } from "./linkedinClient";
import { getSessionHealth, setSessionHealth } from "./store/sessionHealthStore";

export { getSessionHealth };

// Wraps the raw LinkedIn client with two protections most naive scrapers skip:
//
// 1. Rate limiting with jitter — paces requests like a human browsing, not a script firing as
//    fast as jobs arrive. This is enforced here (not per-request in the API layer) so it holds
//    across the whole worker regardless of how many jobs pile up.
// 2. A circuit breaker — after repeated auth/block failures, stop hitting LinkedIn entirely
//    instead of hammering an already-flagged or dead session into a permanent ban.
let nextAvailableAt = 0;

async function throttle(): Promise<void> {
  const now = Date.now();
  const waitMs = Math.max(0, nextAvailableAt - now);
  if (waitMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
  const jitter = Math.random() * config.requestJitterMs;
  nextAvailableAt = Date.now() + config.minRequestIntervalMs + jitter;
}

export async function fetchProfileThroughSession(publicIdentifier: string): Promise<unknown> {
  const health = getSessionHealth();
  if (health.state === "flagged") {
    throw new SessionFlaggedError(health.lastError);
  }

  await throttle();

  try {
    const raw = await fetchProfileView(publicIdentifier);
    setSessionHealth({
      ...health,
      state: "healthy",
      consecutiveFailures: 0,
      lastRequestAt: new Date().toISOString(),
    });
    return raw;
  } catch (err) {
    if (err instanceof LinkedInAuthError || err instanceof LinkedInBlockedError) {
      const consecutiveFailures = health.consecutiveFailures + 1;
      const flagging = consecutiveFailures >= config.sessionFailureThreshold;
      const now = new Date().toISOString();
      setSessionHealth({
        state: flagging ? "flagged" : "healthy",
        consecutiveFailures,
        lastError: err.message,
        lastErrorAt: now,
        flaggedAt: flagging ? now : health.flaggedAt,
        lastRequestAt: now,
      });
    }
    throw err;
  }
}

export function resetSessionHealth(): void {
  setSessionHealth({
    state: "healthy",
    consecutiveFailures: 0,
    lastError: null,
    lastErrorAt: null,
    flaggedAt: null,
    lastRequestAt: null,
  });
}
