import { PARSER_VERSION, parseProfileView } from "./profileParser";
import { latestRawPayloadFor } from "./store/rawPayloadStore";
import { setCached } from "./store/resultCache";
import type { LinkedInProfile } from "./types";

// Demonstrates the payoff of keeping raw payloads: when the parser is fixed/improved, previously
// fetched profiles can be re-normalized from disk — no additional LinkedIn request, no risk to
// the session — and the cache is refreshed with the new parser's output.
export function reparseFromStoredPayload(publicIdentifier: string, profileUrl: string): LinkedInProfile | undefined {
  const rawRecord = latestRawPayloadFor(publicIdentifier);
  if (!rawRecord) return undefined;

  const profile = parseProfileView(rawRecord.raw, publicIdentifier, profileUrl);
  setCached(publicIdentifier, profile, PARSER_VERSION, rawRecord.id);
  return profile;
}
