import { InvalidProfileUrlError } from "./errors";

// Accepts e.g. https://www.linkedin.com/in/john-doe-12345/ or linkedin.com/in/john-doe (with or without scheme/trailing slash/query string).
export function extractPublicIdentifier(profileUrl: string): string {
  let url: URL;
  try {
    url = new URL(profileUrl.startsWith("http") ? profileUrl : `https://${profileUrl}`);
  } catch {
    throw new InvalidProfileUrlError(profileUrl);
  }

  if (!url.hostname.endsWith("linkedin.com")) {
    throw new InvalidProfileUrlError(profileUrl);
  }

  const match = url.pathname.match(/\/in\/([^/]+)/);
  if (!match) {
    throw new InvalidProfileUrlError(profileUrl);
  }

  return decodeURIComponent(match[1]);
}
