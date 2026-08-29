import express, { type NextFunction, type Request, type Response } from "express";
import { config } from "./config";
import { InvalidProfileUrlError, JobNotFoundError } from "./errors";
import { extractPublicIdentifier } from "./profileUrl";
import { reparseFromStoredPayload } from "./reparse";
import { getSessionHealth, resetSessionHealth } from "./sessionManager";
import * as jobStore from "./store/jobStore";
import { getCached } from "./store/resultCache";
import type { JobRecord } from "./types";
import { enqueue } from "./queue/jobQueue";
import { startWorkerLoop } from "./worker";

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Briefly polls the job store so a cache-miss request still looks synchronous when LinkedIn
// responds quickly. If it doesn't finish in time, the caller falls back to polling the job
// endpoint themselves — the client never blocks longer than longPollTimeoutMs on one call.
async function waitForJob(jobId: string): Promise<JobRecord> {
  const deadline = Date.now() + config.longPollTimeoutMs;
  let job = jobStore.getJob(jobId)!;
  while (Date.now() < deadline && (job.status === "queued" || job.status === "processing")) {
    await sleep(config.longPollIntervalMs);
    job = jobStore.getJob(jobId)!;
  }
  return job;
}

app.get("/api/profile", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const profileUrl = req.query.url;
    if (typeof profileUrl !== "string" || profileUrl.trim().length === 0) {
      res.status(400).json({ error: "Query parameter 'url' is required, e.g. ?url=https://www.linkedin.com/in/someone" });
      return;
    }

    const publicIdentifier = extractPublicIdentifier(profileUrl);

    const cached = getCached(publicIdentifier);
    if (cached) {
      res.json({ ...cached.profile, source: "cache", cachedAt: cached.cachedAt, expiresAt: cached.expiresAt });
      return;
    }

    const existingJob = jobStore.findActiveJobFor(publicIdentifier);
    const job = existingJob ?? jobStore.createJob(publicIdentifier, profileUrl);
    if (!existingJob) enqueue(job.id);

    const finalJob = await waitForJob(job.id);

    if (finalJob.status === "completed") {
      res.json({ ...finalJob.result, source: "live" });
      return;
    }
    if (finalJob.status === "failed") {
      res.status(502).json({ error: finalJob.error ?? "LinkedIn fetch failed", jobId: finalJob.id });
      return;
    }

    // Still queued/processing after the long-poll window — hand back a job id to poll instead of
    // holding the connection open indefinitely.
    res.status(202).json({
      jobId: finalJob.id,
      status: finalJob.status,
      statusUrl: `/api/jobs/${finalJob.id}`,
    });
  } catch (err) {
    next(err);
  }
});

app.get("/api/jobs/:id", (req: Request, res: Response, next: NextFunction) => {
  try {
    const job = jobStore.getJob(req.params.id);
    if (!job) throw new JobNotFoundError(req.params.id);

    if (job.status === "failed") {
      res.status(502).json({ id: job.id, status: job.status, error: job.error });
      return;
    }
    if (job.status === "completed") {
      res.json({ id: job.id, status: job.status, result: job.result, updatedAt: job.updatedAt });
      return;
    }
    res.json({ id: job.id, status: job.status, updatedAt: job.updatedAt });
  } catch (err) {
    next(err);
  }
});

// Re-normalizes the most recently stored raw payload for a profile through the current parser,
// without hitting LinkedIn again. Useful right after a parser fix/deploy.
app.post("/api/profile/:publicIdentifier/reparse", (req: Request, res: Response) => {
  const { publicIdentifier } = req.params;
  const profileUrl = `https://www.linkedin.com/in/${publicIdentifier}/`;
  const profile = reparseFromStoredPayload(publicIdentifier, profileUrl);

  if (!profile) {
    res.status(404).json({ error: `No stored raw payload for "${publicIdentifier}" yet — fetch it via /api/profile first.` });
    return;
  }
  res.json({ ...profile, source: "reparsed" });
});

app.get("/api/session/health", (_req: Request, res: Response) => {
  res.json(getSessionHealth());
});

app.post("/api/session/reset", (_req: Request, res: Response) => {
  resetSessionHealth();
  res.json({ status: "reset" });
});

app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof InvalidProfileUrlError) {
    res.status(400).json({ error: err.message });
    return;
  }
  if (err instanceof JobNotFoundError) {
    res.status(404).json({ error: err.message });
    return;
  }

  console.error(err);
  res.status(500).json({ error: "Internal server error" });
});

startWorkerLoop();

app.listen(config.port, () => {
  console.log(`linkedin-profile-api listening on port ${config.port}`);
});
