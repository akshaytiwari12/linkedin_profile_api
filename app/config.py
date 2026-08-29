import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def _strip_quotes(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == '"' and value[-1] == '"' else value


class Config:
    def __init__(self) -> None:
        self.port = int(os.getenv("PORT", "8000"))

        self.li_at = _require("LI_AT_COOKIE")
        # Stored without quotes regardless of how the user pasted it; the two places it's used
        # need different quoting (see linkedin_client) and dotenv strips quotes inconsistently,
        # so normalize once here.
        self.jsessionid = _strip_quotes(_require("LI_JSESSIONID"))

        # curl_cffi impersonation target. Determines the TLS/JA3 + HTTP2 fingerprint we present.
        self.impersonate = os.getenv("IMPERSONATE", "chrome")

        self.data_dir = os.getenv("DATA_DIR", "data")
        self.fixtures_dir = os.getenv("FIXTURES_DIR", "fixtures")

        self.cache_ttl_hours = float(os.getenv("CACHE_TTL_HOURS", "48"))

        # Minimum spacing between real LinkedIn requests plus random jitter, so the request
        # cadence looks like a human browsing rather than a script. Defaults are deliberately
        # conservative: an invalidated session costs a manual browser re-login.
        self.min_request_interval_s = float(os.getenv("MIN_REQUEST_INTERVAL_S", "12"))
        self.request_jitter_s = float(os.getenv("REQUEST_JITTER_S", "8"))

        self.session_failure_threshold = int(os.getenv("SESSION_FAILURE_THRESHOLD", "2"))

        self.long_poll_timeout_s = float(os.getenv("LONG_POLL_TIMEOUT_S", "25"))
        self.long_poll_interval_s = float(os.getenv("LONG_POLL_INTERVAL_S", "0.3"))


config = Config()
