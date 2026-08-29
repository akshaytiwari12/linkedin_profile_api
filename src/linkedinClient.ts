import { config } from "./config";
import { LinkedInAuthError, LinkedInBlockedError, ProfileNotFoundError } from "./errors";

const BROWSER_USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

const BASE_URL = "https://www.linkedin.com/voyager/api";

function csrfTokenFromJsessionId(jsessionId: string): string {
  // LinkedIn stores JSESSIONID wrapped in double quotes; the csrf-token header must match it exactly, quotes included.
  return jsessionId;
}

function buildHeaders(): Record<string, string> {
  return {
    Cookie: `li_at=${config.liAtCookie}; JSESSIONID=${config.jsessionId}`,
    "csrf-token": csrfTokenFromJsessionId(config.jsessionId),
    accept: "application/vnd.linkedin.normalized+json+2.1",
    "x-restli-protocol-version": "2.0.0",
    "x-li-lang": "en_US",
    "user-agent": BROWSER_USER_AGENT,
    referer: "https://www.linkedin.com/",
  };
}

async function voyagerGet(path: string): Promise<unknown> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "GET",
    headers: buildHeaders(),
    // An invalid/expired session gets redirected to the login page rather than a clean 401 — treat
    // any redirect as an auth failure instead of following it into an HTML page.
    redirect: "manual",
  });

  if (response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400)) {
    throw new LinkedInAuthError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new LinkedInAuthError();
  }
  // LinkedIn returns HTTP 999 (non-standard) when it flags a request as automated/abusive.
  if (response.status === 999 || response.status === 429) {
    throw new LinkedInBlockedError();
  }
  if (response.status === 404) {
    throw new ProfileNotFoundError(path);
  }
  if (!response.ok) {
    throw new Error(`LinkedIn request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export async function fetchProfileView(publicIdentifier: string): Promise<unknown> {
  try {
    return await voyagerGet(`/identity/profiles/${encodeURIComponent(publicIdentifier)}/profileView`);
  } catch (err) {
    if (err instanceof ProfileNotFoundError) {
      throw new ProfileNotFoundError(publicIdentifier);
    }
    throw err;
  }
}
