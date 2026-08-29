import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { config } from "../config";
import type { RawPayloadRecord } from "../types";
import { JsonTable } from "./jsonTable";

// Immutable log of every raw LinkedIn response ever fetched. Kept separate from the parsed
// result so a parser bug or LinkedIn schema change can be fixed and replayed against this data
// without spending another LinkedIn request. See profileParser.reparse().
const table = new JsonTable<RawPayloadRecord>(join(config.dataDir, "raw-payloads.json"));

export function saveRawPayload(publicIdentifier: string, raw: unknown): RawPayloadRecord {
  const record: RawPayloadRecord = {
    id: randomUUID(),
    publicIdentifier,
    fetchedAt: new Date().toISOString(),
    raw,
  };
  table.set(record.id, record);
  return record;
}

export function getRawPayload(id: string): RawPayloadRecord | undefined {
  return table.get(id);
}

export function latestRawPayloadFor(publicIdentifier: string): RawPayloadRecord | undefined {
  const matches = table.values().filter((record) => record.publicIdentifier === publicIdentifier);
  matches.sort((a, b) => b.fetchedAt.localeCompare(a.fetchedAt));
  return matches[0];
}
