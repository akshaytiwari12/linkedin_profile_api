import { join } from "node:path";
import { config } from "../config";
import type { SessionHealthRecord } from "../types";
import { JsonTable } from "./jsonTable";

const table = new JsonTable<SessionHealthRecord>(join(config.dataDir, "session-health.json"));
const KEY = "default"; // single-session for this project; keyed for a future session pool.

const initial: SessionHealthRecord = {
  state: "healthy",
  consecutiveFailures: 0,
  lastError: null,
  lastErrorAt: null,
  flaggedAt: null,
  lastRequestAt: null,
};

export function getSessionHealth(): SessionHealthRecord {
  return table.get(KEY) ?? initial;
}

export function setSessionHealth(record: SessionHealthRecord): void {
  table.set(KEY, record);
}
