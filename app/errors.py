class LinkedInAuthError(Exception):
    """Session rejected. LinkedIn answers an invalid/expired session with a 302 to the login
    page rather than a clean 401, so redirects are treated as auth failures."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "LinkedIn session is invalid or expired. Re-login in a browser and refresh "
            "LI_AT_COOKIE / LI_JSESSIONID."
        )


class LinkedInBlockedError(Exception):
    """LinkedIn flagged the request as automated (HTTP 999) or rate-limited it (429)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "LinkedIn blocked this request (bot/anomaly detection). Back off and retry later."
        )


class ProfileNotFoundError(Exception):
    def __init__(self, public_identifier: str) -> None:
        super().__init__(f'No LinkedIn profile found for identifier "{public_identifier}".')


class InvalidProfileUrlError(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(
            f'"{url}" is not a recognizable LinkedIn profile URL '
            "(expected https://www.linkedin.com/in/<identifier>)."
        )


class SessionFlaggedError(Exception):
    """Circuit breaker is open — we stop sending requests rather than push an already-flagged
    session further toward a hard account restriction."""

    def __init__(self, reason: str | None) -> None:
        super().__init__(
            f"LinkedIn session circuit breaker is open ({reason or 'too many failures'}). "
            "Refresh LI_AT_COOKIE / LI_JSESSIONID, then POST /api/session/reset."
        )


class JobNotFoundError(Exception):
    def __init__(self, job_id: str) -> None:
        super().__init__(f'No job found with id "{job_id}".')
