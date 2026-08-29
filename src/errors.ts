export class LinkedInAuthError extends Error {
  constructor(message = "LinkedIn session is invalid or expired. Re-login in a browser and refresh LI_AT_COOKIE / LI_JSESSIONID.") {
    super(message);
    this.name = "LinkedInAuthError";
  }
}

export class LinkedInBlockedError extends Error {
  constructor(message = "LinkedIn blocked this request (bot/anomaly detection). Back off and retry later.") {
    super(message);
    this.name = "LinkedInBlockedError";
  }
}

export class ProfileNotFoundError extends Error {
  constructor(publicIdentifier: string) {
    super(`No LinkedIn profile found for identifier "${publicIdentifier}".`);
    this.name = "ProfileNotFoundError";
  }
}

export class InvalidProfileUrlError extends Error {
  constructor(url: string) {
    super(`"${url}" is not a recognizable LinkedIn profile URL (expected https://www.linkedin.com/in/<identifier>).`);
    this.name = "InvalidProfileUrlError";
  }
}

export class SessionFlaggedError extends Error {
  constructor(reason: string | null) {
    super(
      `LinkedIn session circuit breaker is open (${reason ?? "too many failures"}). ` +
        `Refresh LI_AT_COOKIE / LI_JSESSIONID, then POST /api/session/reset.`
    );
    this.name = "SessionFlaggedError";
  }
}

export class JobNotFoundError extends Error {
  constructor(jobId: string) {
    super(`No job found with id "${jobId}".`);
    this.name = "JobNotFoundError";
  }
}
