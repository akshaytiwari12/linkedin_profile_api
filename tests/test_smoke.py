"""Offline smoke tests. No LinkedIn requests — everything runs against a synthetic payload.

Run:  python3 -m tests.test_smoke
"""

import json
import sys

from app.profile_parser import parse_profile_view
from app.profile_url import extract_public_identifier
from app.errors import InvalidProfileUrlError

SYNTHETIC_PAYLOAD = {
    "included": [
        {
            "$type": "com.linkedin.voyager.identity.profile.Profile",
            "firstName": "Jane",
            "lastName": "Doe",
            "headline": "Engineer at Example Corp",
            "geoLocationName": "San Francisco, CA",
            "summary": "Building things.",
            "profilePicture": {
                "displayImageReference": {
                    "vectorImage": {
                        "rootUrl": "https://media.licdn.com/dms/image/",
                        "artifacts": [
                            {"width": 200, "height": 200, "fileIdentifyingUrlPathSegment": "abc123"}
                        ],
                    }
                }
            },
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Position",
            "title": "Software Engineer",
            "companyName": "Example Corp",
            "locationName": "SF",
            "description": "Did stuff.",
            "timePeriod": {"startDate": {"month": 1, "year": 2022}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Education",
            "schoolName": "Example University",
            "degreeName": "B.S.",
            "fieldOfStudy": "Computer Science",
            "timePeriod": {"startDate": {"year": 2016}, "endDate": {"year": 2020}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Skill",
            "name": "TypeScript",
            "endorsementCount": 12,
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Certification",
            "name": "AWS Certified Developer",
            "authority": "Amazon Web Services",
            "timePeriod": {"startDate": {"month": 6, "year": 2023}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Language",
            "name": "English",
            "proficiency": "NATIVE_OR_BILINGUAL",
        },
    ]
}

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

    for bad in ("not-a-url", "https://evil.com/in/john-doe", "https://www.linkedin.com/company/x"):
        try:
            extract_public_identifier(bad)
            print(f"  FAIL  rejects {bad!r}: no error raised")
            failures.append(f"rejects {bad}")
        except InvalidProfileUrlError:
            print(f"  PASS  rejects {bad!r}")


def test_parser() -> None:
    print("\nParser:")
    p = parse_profile_view(SYNTHETIC_PAYLOAD, "jane-doe", "https://www.linkedin.com/in/jane-doe/")
    check("fullName", p["fullName"], "Jane Doe")
    check("headline", p["headline"], "Engineer at Example Corp")
    check("location", p["location"], "San Francisco, CA")
    check("about", p["about"], "Building things.")
    check("image url", p["profileImages"][0]["url"], "https://media.licdn.com/dms/image/abc123")
    check("experience count", len(p["experience"]), 1)
    check("isCurrent", p["experience"][0]["isCurrent"], True)
    check("education endYear", p["education"][0]["endYear"], 2020)
    check("skills", p["skills"], [{"name": "TypeScript", "endorsementCount": 12}])
    check("certification", p["certifications"][0]["name"], "AWS Certified Developer")
    check("language", p["languages"][0]["name"], "English")


def test_parser_tolerates_empty() -> None:
    print("\nParser resilience (empty / unexpected payload):")
    p = parse_profile_view({}, "nobody", "https://www.linkedin.com/in/nobody/")
    check("empty payload -> null name", p["fullName"], None)
    check("empty payload -> [] experience", p["experience"], [])
    p2 = parse_profile_view({"included": [{"$type": "com.linkedin.Unknown"}]}, "x", "u")
    check("unknown entity ignored", p2["experience"], [])


if __name__ == "__main__":
    test_url_parsing()
    test_parser()
    test_parser_tolerates_empty()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        sys.exit(1)
    print("All smoke tests passed.")
