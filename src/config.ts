import "dotenv/config";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required environment variable: ${name}. Copy .env.example to .env and fill it in.`
    );
  }
  return value;
}

export const config = {
  port: Number(process.env.PORT ?? 3000),
  liAtCookie: requireEnv("LI_AT_COOKIE"),
  jsessionId: requireEnv("LI_JSESSIONID"),

  dataDir: process.env.DATA_DIR ?? "data",

  // How long a fetched profile stays in the result cache before it's considered stale.
  cacheTtlHours: Number(process.env.CACHE_TTL_HOURS ?? 48),

  // Minimum spacing between real LinkedIn requests, plus random jitter on top, so the worker
  // paces itself like a human browsing rather than firing requests back to back.
  minRequestIntervalMs: Number(process.env.MIN_REQUEST_INTERVAL_MS ?? 4000),
  requestJitterMs: Number(process.env.REQUEST_JITTER_MS ?? 3000),

  // Consecutive LinkedIn auth/block failures before the session circuit breaker trips and stops
  // sending further requests until someone resets it (after refreshing the cookie).
  sessionFailureThreshold: Number(process.env.SESSION_FAILURE_THRESHOLD ?? 2),

  // The API gateway briefly long-polls a freshly enqueued job before falling back to 202 + jobId,
  // so most cache-miss requests still get a synchronous-looking response.
  longPollTimeoutMs: Number(process.env.LONG_POLL_TIMEOUT_MS ?? 8000),
  longPollIntervalMs: Number(process.env.LONG_POLL_INTERVAL_MS ?? 300),
};
