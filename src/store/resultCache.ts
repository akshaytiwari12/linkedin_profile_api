import { join } from "node:path";
import { config } from "../config";
import type { CachedProfileRecord, LinkedInProfile } from "../types";
import { JsonTable } from "./jsonTable";

// Structured, TTL'd cache of parsed profiles. This is what most requests should hit — it's the
// reason repeat lookups of the same profile don't cost another LinkedIn request.
const table = new JsonTable<CachedProfileRecord>(join(config.dataDir, "result-cache.json"));

export function getCached(publicIdentifier: string): CachedProfileRecord | undefined {
  const record = table.get(publicIdentifier);
  if (!record) return undefined;
  if (new Date(record.expiresAt).getTime() < Date.now()) return undefined;
  return record;
}

export function setCached(
  publicIdentifier: string,
  profile: LinkedInProfile,
  parserVersion: number,
  rawPayloadId: string
): CachedProfileRecord {
  const now = new Date();
  const record: CachedProfileRecord = {
    publicIdentifier,
    profile,
    parserVersion,
    rawPayloadId,
    cachedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + config.cacheTtlHours * 60 * 60 * 1000).toISOString(),
  };
  table.set(publicIdentifier, record);
  return record;
}
