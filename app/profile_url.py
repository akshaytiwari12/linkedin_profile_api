import re
from urllib.parse import unquote, urlparse

from .errors import InvalidProfileUrlError

_IN_PATH = re.compile(r"/in/([^/]+)")


def extract_public_identifier(profile_url: str) -> str:
    """Accepts https://www.linkedin.com/in/john-doe/, linkedin.com/in/john-doe?x=1, etc.

    The linkedin.com host check is deliberate: this value comes straight from a query parameter,
    so without it the service would happily fetch any URL a caller supplies (SSRF).
    """
    candidate = profile_url if profile_url.startswith("http") else f"https://{profile_url}"
    parsed = urlparse(candidate)

    hostname = (parsed.hostname or "").lower()
    if not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
        raise InvalidProfileUrlError(profile_url)

    match = _IN_PATH.search(parsed.path)
    if not match:
        raise InvalidProfileUrlError(profile_url)

    return unquote(match.group(1))
