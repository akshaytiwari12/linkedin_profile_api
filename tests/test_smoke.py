"""Offline tests for profile-URL parsing, including the SSRF guard.

The identifier comes straight from a caller-supplied query parameter, so the host check is a
security control rather than a convenience — without it the service would fetch any URL given
to it.

Run:  python3 -m tests.test_smoke
"""

import sys

from app.errors import InvalidProfileUrlError
from app.profile_url import extract_public_identifier

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        failures.append(label)


def test_url_parsing() -> None:
    print("URL parsing:")
    check("full url", extract_public_identifier("https://www.linkedin.com/in/john-doe/"), "john-doe")
    check("no scheme", extract_public_identifier("linkedin.com/in/john-doe"), "john-doe")
    check(
        "query string",
        extract_public_identifier("https://www.linkedin.com/in/john-doe?trk=abc"),
        "john-doe",
    )
    check(
        "regional subdomain",
        extract_public_identifier("https://in.linkedin.com/in/john-doe"),
        "john-doe",
    )
    check(
        "url-encoded identifier",
        extract_public_identifier("https://www.linkedin.com/in/jos%C3%A9-doe"),
        "josé-doe",
    )


def test_rejects_non_profiles() -> None:
    print("\nRejects non-profile and off-host URLs (SSRF guard):")
    for bad in (
        "not-a-url",
        "https://evil.com/in/john-doe",
        # Suffix match on "linkedin.com" alone would accept this; the check is on the hostname.
        "https://linkedin.com.evil.com/in/john-doe",
        "https://www.linkedin.com/company/example",
        "",
    ):
        try:
            extract_public_identifier(bad)
            print(f"  FAIL  rejects {bad!r}: no error raised")
            failures.append(f"rejects {bad}")
        except InvalidProfileUrlError:
            print(f"  PASS  rejects {bad!r}")


if __name__ == "__main__":
    test_url_parsing()
    test_rejects_non_profiles()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        sys.exit(1)
    print("All URL tests passed.")
