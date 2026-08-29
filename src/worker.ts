import { dequeue } from "./queue/jobQueue";
import { PARSER_VERSION, parseProfileView } from "./profileParser";
import { fetchProfileThroughSession } from "./sessionManager";
import * as jobStore from "./store/jobStore";
import { saveRawPayload } from "./store/rawPayloadStore";
import { setCached } from "./store/resultCache";

const IDLE_POLL_MS = 200;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function processJob(jobId: string): Promise<void> {
  const job = jobStore.getJob(jobId);
  if (!job) return;

  jobStore.markProcessing(jobId);

  try {
    const raw = await fetchProfileThroughSession(job.publicIdentifier);
    const rawRecord = saveRawPayload(job.publicIdentifier, raw);
    const profile = parseProfileView(raw, job.publicIdentifier, job.profileUrl);

    setCached(job.publicIdentifier, profile, PARSER_VERSION, rawRecord.id);
    jobStore.markCompleted(jobId, profile);
  } catch (err) {
    jobStore.markFailed(jobId, err instanceof Error ? err.message : String(err));
  }
}

let started = false;

// One worker processing jobs strictly one at a time — matches the fact that we're pacing a
// single LinkedIn session. If this ever needs more throughput, add more sessions to the pool
// and run one loop per session, not more concurrency on a single session.
export function startWorkerLoop(): void {
  if (started) return;
  started = true;

  void (async () => {
    for (;;) {
      const jobId = dequeue();
      if (!jobId) {
        await sleep(IDLE_POLL_MS);
        continue;
      }
      await processJob(jobId);
    }
  })();
}
