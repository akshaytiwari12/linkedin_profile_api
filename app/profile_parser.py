from datetime import datetime, timezone
from typing import Any

# Bump when parsing logic changes, so cached records stay traceable to the parser that produced
# them and re-parsed results are distinguishable from live ones.
PARSER_VERSION = 1


def _entities(response: dict[str, Any], type_suffix: str) -> list[dict[str, Any]]:
    """Voyager responses are a flat `included` list of typed entities rather than one nested
    profile object; each entity carries a `$type` like
    com.linkedin.voyager.identity.profile.Position. Filtering by type suffix (rather than an
    exact string) keeps this working if LinkedIn re-namespaces the entities."""
    return [e for e in response.get("included", []) if str(e.get("$type", "")).endswith(type_suffix)]


def _first(response: dict[str, Any], type_suffix: str) -> dict[str, Any] | None:
    found = _entities(response, type_suffix)
    return found[0] if found else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _date(value: Any) -> dict[str, int | None] | None:
    if not isinstance(value, dict):
        return None
    if "month" not in value and "year" not in value:
        return None
    return {"month": value.get("month"), "year": value.get("year")}


def _time_period(entity: dict[str, Any]) -> tuple[Any, Any]:
    period = entity.get("timePeriod") or {}
    return _date(period.get("startDate")), _date(period.get("endDate"))


def _profile_images(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not profile:
        return []
    vector = (
        (profile.get("profilePicture") or {})
        .get("displayImageReference", {})
        .get("vectorImage")
    )
    if not vector or not vector.get("rootUrl"):
        return []

    images = []
    for artifact in vector.get("artifacts") or []:
        segment = artifact.get("fileIdentifyingUrlPathSegment")
        if not segment:
            continue
        images.append(
            {
                "url": f"{vector['rootUrl']}{segment}",
                "width": artifact.get("width"),
                "height": artifact.get("height"),
            }
        )
    return images


def parse_profile_view(raw: Any, public_identifier: str, profile_url: str) -> dict[str, Any]:
    response: dict[str, Any] = raw if isinstance(raw, dict) else {}
    profile = _first(response, "identity.profile.Profile") or {}

    first_name = _text(profile.get("firstName"))
    last_name = _text(profile.get("lastName"))
    full_name = " ".join(p for p in (first_name, last_name) if p) or None

    experience = []
    for position in _entities(response, "Position"):
        start, end = _time_period(position)
        experience.append(
            {
                "title": _text(position.get("title")),
                "companyName": _text(position.get("companyName")),
                "location": _text(position.get("locationName")),
                "description": _text(position.get("description")),
                "startDate": start,
                "endDate": end,
                "isCurrent": end is None and start is not None,
            }
        )

    education = []
    for school in _entities(response, "Education"):
        start, end = _time_period(school)
        education.append(
            {
                "schoolName": _text(school.get("schoolName")),
                "degreeName": _text(school.get("degreeName")),
                "fieldOfStudy": _text(school.get("fieldOfStudy")),
                "startYear": (start or {}).get("year"),
                "endYear": (end or {}).get("year"),
                "description": _text(school.get("description")),
            }
        )

    certifications = []
    for cert in _entities(response, "Certification"):
        start, end = _time_period(cert)
        certifications.append(
            {
                "name": _text(cert.get("name")),
                "authority": _text(cert.get("authority")),
                "startDate": start,
                "endDate": end,
            }
        )

    return {
        "publicIdentifier": public_identifier,
        "profileUrl": profile_url,
        "firstName": first_name,
        "lastName": last_name,
        "fullName": full_name,
        "headline": _text(profile.get("headline")),
        "location": _text(profile.get("geoLocationName")) or _text(profile.get("locationName")),
        "about": _text(profile.get("summary")),
        "profileImages": _profile_images(profile),
        "experience": experience,
        "education": education,
        "skills": [
            {"name": _text(s.get("name")), "endorsementCount": s.get("endorsementCount")}
            for s in _entities(response, "Skill")
            if _text(s.get("name"))
        ],
        "certifications": certifications,
        "languages": [
            {"name": _text(l.get("name")), "proficiency": _text(l.get("proficiency"))}
            for l in _entities(response, "Language")
            if _text(l.get("name"))
        ],
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }
