import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { config } from "../config";
import type { JobRecord, LinkedInProfile } from "../types";
import { JsonTable } from "./jsonTable";

const table = new JsonTable<JobRecord>(join(config.dataDir, "jobs.json"));

export function createJob(publicIdentifier: string, profileUrl: string): JobRecord {
  const now = new Date().toISOString();
  const job: JobRecord = {
    id: randomUUID(),
    publicIdentifier,
    profileUrl,
    status: "queued",
    createdAt: now,
    updatedAt: now,
  };
  table.set(job.id, job);
  return job;
}

export function getJob(id: string): JobRecord | undefined {
  return table.get(id);
}

// Avoids piling up duplicate LinkedIn fetches when several requests for the same profile arrive
// before the first one finishes.
export function findActiveJobFor(publicIdentifier: string): JobRecord | undefined {
  return table
    .values()
    .find((job) => job.publicIdentifier === publicIdentifier && (job.status === "queued" || job.status === "processing"));
}

export function markProcessing(id: string): void {
  const job = table.get(id);
  if (!job) return;
  table.set(id, { ...job, status: "processing", updatedAt: new Date().toISOString() });
}

export function markCompleted(id: string, result: LinkedInProfile): void {
  const job = table.get(id);
  if (!job) return;
  table.set(id, { ...job, status: "completed", result, updatedAt: new Date().toISOString() });
}

export function markFailed(id: string, error: string): void {
  const job = table.get(id);
  if (!job) return;
  table.set(id, { ...job, status: "failed", error, updatedAt: new Date().toISOString() });
}
