"""Parse a LinkedIn mwlite profile page into the API's structured schema.

Why HTML and not JSON: LinkedIn retired the JSON profile endpoints this project originally
targeted (`profileView` answers 410, the dash endpoints 302) and the mwlite page server-renders
the profile rather than fetching it client-side, so there is no profile GraphQL query to call.
The markup is what LinkedIn actually returns today.

Selector strategy: anchor on LinkedIn's *semantic* component classes (`profile-entity-lockup`,
`skill-item`, `list-item-heading`) rather than layout/utility classes, and locate sections by
their visible heading text rather than position. Both survive cosmetic redesigns better than
structural selectors would, though neither is as durable as a JSON contract — see README
"Known limitations".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup, Tag

PARSER_VERSION = 2

# LinkedIn caps headlines at 220 characters; anything longer is a different field.
MAX_HEADLINE_LEN = 250

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ],
        start=1,
    )
}

# "Jan 2022 - Present", "2019 - 2023", "Mar 2020 - Aug 2021 · 1 yr 6 mos"
_DATE_RANGE = re.compile(
    r"(?P<start>(?:[A-Za-z]{3,9}\s+)?\d{4})\s*[-–—]\s*(?P<end>Present|(?:[A-Za-z]{3,9}\s+)?\d{4})",
    re.I,
)

SECTION_ALIASES = {
    "experience": "experience",
    "education": "education",
    "licenses & certifications": "certifications",
    "licenses and certifications": "certifications",
    "certifications": "certifications",
    "languages": "languages",
    "skills": "skills",
}


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _parse_month_year(token: str) -> dict[str, int | None] | None:
    token = token.strip()
    if not token or token.lower() == "present":
        return None
    month_match = re.match(r"([A-Za-z]{3,9})\s+(\d{4})", token)
    if month_match:
        return {
            "month": MONTHS.get(month_match.group(1)[:3].lower()),
            "year": int(month_match.group(2)),
        }
    year_match = re.match(r"(\d{4})", token)
    if year_match:
        return {"month": None, "year": int(year_match.group(1))}
    return None


def _extract_dates(text: str) -> tuple[dict | None, dict | None, bool]:
    """Returns (start, end, is_current) from a metadata line."""
    match = _DATE_RANGE.search(text or "")
    if not match:
        return None, None, False
    start = _parse_month_year(match.group("start"))
    end_token = match.group("end")
    is_current = end_token.strip().lower() == "present"
    end = None if is_current else _parse_month_year(end_token)
    return start, end, is_current


def _lockup_lines(lockup: Tag) -> list[str]:
    """Visible text lines of an entity lockup, in document order, de-duplicated.

    Screen-reader-only nodes are dropped — they repeat the visible text and would otherwise
    double every field.
    """
    for hidden in lockup.select(".sr-only, .visually-hidden"):
        hidden.decompose()

    lines: list[str] = []
    for node in lockup.find_all(["h2", "h3", "span", "p", "div"]):
        if node.find(["h2", "h3", "span", "p", "div"]):
            continue  # keep leaf nodes only, so text isn't captured at every ancestor level
        text = _clean(node.get_text(" ", strip=True))
        if text and text not in lines:
            lines.append(text)
    return lines


# "2 yrs 8 mos", "11 mos", "1 yr"
_DURATION = re.compile(r"^\d+\s*(?:yrs?|mos?|years?|months?)(?:\s+\d+\s*(?:yrs?|mos?))?$", re.I)
# Collapsible-text affordances that would otherwise be mistaken for content.
_UI_NOISE = re.compile(r"^(?:…\s*more|see\s+more|see\s+less|…)$", re.I)
# A date fragment on its own line, e.g. "Jan 2024 -" or "Present"
_DATE_FRAGMENT = re.compile(r"^(?:(?:[A-Za-z]{3,9}\s+)?\d{4}\s*[-–—]?|Present)$", re.I)


# Top-card chrome that sits between the name, headline and location: connection counts, action
# buttons, and degree-of-connection badges.
_TOPCARD_NOISE = re.compile(
    r"^(?:\d[\d,]*\+?\s*(?:connections?|followers?)"
    r"|connect|message|follow(?:ing)?|contact(?: info)?|more|save|share"
    r"|\d+(?:st|nd|rd|th)|[a-z0-9]{1,3})$",
    re.I,
)


# The top card's location row ends with the member's connection/follower count
# ("Pune Division, Maharashtra, India 500+ connections"); splitting there yields the location and
# also distinguishes that row from the school/company row above it.
_CONNECTION_COUNT = re.compile(r"\s*\d[\d,]*\+?\s*(?:connections?|followers?)\s*$", re.I)


# The collapse/expand affordances render inside the text block, so they arrive appended to the
# content rather than as separate lines: "...ready solutions. …See more See less" or "...etc. …more".
# Anchored to a trailing ellipsis or the literal "see" so a description genuinely ending in the
# word "more" is left alone.
_TRAILING_UI_NOISE = re.compile(
    r"(?:\s*(?:…\s*(?:see\s+)?more|see\s+more|see\s+less|…))+\s*$", re.I
)


def _strip_ui_noise(text: str | None) -> str | None:
    cleaned = _clean(text)
    if not cleaned:
        return None
    cleaned = _TRAILING_UI_NOISE.sub("", cleaned).strip()
    return cleaned or None


def _is_locationish(text: str) -> bool:
    """Location lines are short and comma-delimited ("Bengaluru, Karnataka, India"), which
    distinguishes them from descriptions and from company names."""
    return "," in text and len(text) < 120 and not _DATE_RANGE.search(text)


def _parse_entity(lockup: Tag) -> dict[str, Any]:
    heading = lockup.select_one(".list-item-heading, h3, h2")
    title = _clean(heading.get_text(" ", strip=True)) if heading else None

    raw_lines = [l for l in _lockup_lines(lockup) if l != title]
    lines = [l for l in raw_lines if not _UI_NOISE.match(l)]

    # Dates are split across sibling spans ("Jan 2024 -" / "Present"), so match against the
    # joined text rather than any single line.
    start, end, is_current = _extract_dates(" ".join(lines))
    if not start and not end and not is_current:
        start, end, is_current = _extract_dates(lockup.get_text(" ", strip=True))

    # Everything that isn't a date fragment, a duration, or the description is a candidate for
    # the org/location fields.
    meta = [
        l
        for l in lines
        if not _DATE_FRAGMENT.match(l) and not _DURATION.match(l) and not _DATE_RANGE.search(l)
    ]

    summary = lockup.select_one(".truncated-summary, .whitespace-pre-line")
    description = _clean(summary.get_text(" ", strip=True)) if summary else None
    if description:
        description = _UI_NOISE.sub("", description).strip() or None

    location = next((l for l in meta if _is_locationish(l)), None)

    # The org/school is the first non-location, non-description metadata line.
    subtitle = next(
        (
            l
            for l in meta
            if l != location and (not description or l not in description) and len(l) < 160
        ),
        None,
    )

    # Remaining short metadata lines (e.g. degree field for education entries).
    extras = [l for l in meta if l not in (subtitle, location) and len(l) < 120]

    return {
        "title": title,
        "subtitle": subtitle,
        "location": location,
        "description": description,
        "startDate": start,
        "endDate": end,
        "isCurrent": is_current,
        "extras": extras,
    }


def _parse_experience_lockup(lockup: Tag) -> list[dict[str, Any]]:
    """Expand one Experience lockup into an entry per role.

    LinkedIn groups positions by employer: the lockup's `list-item-heading` is the *company*,
    and each role held there is a `body-small-bold` span followed by its own dates and location.
    Reading the heading as the job title (the obvious guess) inverts title and company on every
    entry, and collapsing the lockup to a single entry silently drops every role after the first
    for anyone promoted within a company.
    """
    for hidden in lockup.select(".sr-only, .visually-hidden"):
        hidden.decompose()

    heading = lockup.select_one(".list-item-heading")
    company = _clean(heading.get_text(" ", strip=True)) if heading else None

    # Walk the leaves in order, starting a new role at each bold role span.
    roles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for node in lockup.find_all(["span", "div", "p"]):
        if node.find(["span", "div", "p"]):
            continue
        text = _clean(node.get_text(" ", strip=True))
        if not text or _UI_NOISE.match(text):
            continue

        parent_classes = set(node.parent.get("class") or [])
        if "list-item-heading" in parent_classes:
            continue  # the company heading itself

        if "body-small-bold" in parent_classes:
            if current:
                roles.append(current)
            current = {"title": text, "lines": [], "location": None}
            continue

        if current is None:
            continue

        if "text-color-text-low-emphasis" in parent_classes and _is_locationish(text):
            current["location"] = current["location"] or text
        else:
            current["lines"].append(text)

    if current:
        roles.append(current)

    # Ungrouped lockup (no bold role spans): the heading is the title after all.
    if not roles:
        entity = _parse_entity(lockup)
        return [
            {
                "title": entity["title"],
                "companyName": entity["subtitle"],
                "location": entity["location"],
                "description": entity["description"],
                "startDate": entity["startDate"],
                "endDate": entity["endDate"],
                "isCurrent": entity["isCurrent"],
            }
        ]

    summary = lockup.select_one(".truncated-summary, .whitespace-pre-line")
    description = _strip_ui_noise(summary.get_text(" ", strip=True)) if summary else None

    entries = []
    for role in roles:
        start, end, is_current = _extract_dates(" ".join(role["lines"]))
        entries.append(
            {
                "title": role["title"],
                "companyName": company,
                "location": role["location"],
                # A grouped lockup carries at most one description block; attach it to the
                # current role rather than duplicating it across every position.
                "description": description if is_current else None,
                "startDate": start,
                "endDate": end,
                "isCurrent": is_current,
            }
        )
    return entries


def _section_buckets(soup: BeautifulSoup) -> dict[str, list[Tag]]:
    """Group entity lockups under the section whose heading precedes them.

    Lockups are <li> elements, so rather than walking the tree looking for containers we take
    each lockup and search backwards for its nearest heading. That is also robust to the
    sections being re-nested, which a container-based walk would not be.
    """
    buckets: dict[str, list[Tag]] = {}

    for lockup in soup.select(".profile-entity-lockup"):
        heading = lockup.find_previous(["h2", "h3"])
        label = (_clean(heading.get_text(" ", strip=True)) or "").lower() if heading else ""
        mapped = SECTION_ALIASES.get(label)
        if mapped:
            buckets.setdefault(mapped, []).append(lockup)

    return buckets


def _items_under_heading(soup: BeautifulSoup, *labels: str) -> list[Tag]:
    """List items that follow a given section heading, up to the next heading.

    Certifications and Languages render as plain list items under an <h3>, without the
    entity-lockup wrapper the Experience/Education sections use.
    """
    wanted = {l.lower() for l in labels}
    items: list[Tag] = []

    for heading in soup.find_all(["h2", "h3"]):
        label = (_clean(heading.get_text(" ", strip=True)) or "").lower()
        if label not in wanted:
            continue
        for node in heading.find_all_next(["li", "h2", "h3"]):
            if node.name in ("h2", "h3"):
                break  # reached the next section
            if "skill-item" in (node.get("class") or []):
                continue
            items.append(node)

    return items


def _profile_images(soup: BeautifulSoup) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-delayed-url") or ""
        if "media.licdn.com" not in src or src in seen:
            continue
        seen.add(src)
        images.append({"url": src, "width": None, "height": None})
    return images[:5]


def parse_profile_html(html: str, public_identifier: str, profile_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    name_el = soup.select_one("h1.heading-large, h1")
    full_name = _clean(name_el.get_text(" ", strip=True)) if name_el else None
    first_name = last_name = None
    if full_name:
        parts = full_name.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:]) or None

    # The top card is a container whose direct children are the fields, in a consistent order:
    #
    #   div.flex.items-center                    the name
    #   div.body-small.text-color-text           the headline
    #   div.body-small.…low-emphasis             school or current company
    #   div.body-small.…low-emphasis             location, with the connection count appended
    #
    # Read the containers rather than their leaf nodes: the location div wraps child elements, so
    # a leaf-only walk skips it entirely and the field silently comes back empty. The two
    # low-emphasis rows are told apart by the trailing "N connections" — that row is the location.
    headline = location = current_company = None
    if name_el:
        card = name_el.parent.parent if name_el.parent else None
        for child in card.find_all(recursive=False) if card else []:
            classes = set(child.get("class") or [])
            if "body-small" not in classes:
                continue

            text = _clean(child.get_text(" ", strip=True))
            if not text:
                continue

            if "text-color-text-low-emphasis" in classes:
                match = _CONNECTION_COUNT.search(text)
                if match:
                    location = location or (text[: match.start()].strip() or None)
            elif "text-color-text" in classes:
                headline = headline or text

        company_el = soup.select_one(".member-current-company")
        current_company = (
            _clean(company_el.get_text(" ", strip=True)) if company_el else None
        )

    # NB: #about-profile is a hidden "About this profile" bottom-sheet modal, not the summary.
    # The real About text is a truncated-summary that sits outside any entity lockup.
    about = None
    about_heading = next(
        (
            h
            for h in soup.find_all(["h2", "h3"])
            if (_clean(h.get_text(" ", strip=True)) or "").lower() == "about"
        ),
        None,
    )
    if about_heading:
        node = about_heading.find_next(
            lambda t: isinstance(t, Tag)
            and (
                "truncated-summary" in (t.get("class") or [])
                or "whitespace-pre-line" in (t.get("class") or [])
            )
        )
        about = _strip_ui_noise(node.get_text(" ", strip=True)) if node else None

    if not about:
        for candidate in soup.select(".truncated-summary, .whitespace-pre-line"):
            if candidate.find_parent(class_="profile-entity-lockup"):
                continue
            text = _strip_ui_noise(candidate.get_text(" ", strip=True))
            if text and len(text) > 40:
                about = text
                break

    buckets = _section_buckets(soup)

    experience = []
    for lockup in buckets.get("experience", []):
        experience.extend(_parse_experience_lockup(lockup))

    education = []
    for lockup in buckets.get("education", []):
        e = _parse_entity(lockup)
        # Education lockups list school, then degree, then field of study on separate lines.
        education.append(
            {
                "schoolName": e["title"],
                "degreeName": e["subtitle"],
                "fieldOfStudy": e["extras"][0] if e["extras"] else None,
                "startYear": (e["startDate"] or {}).get("year"),
                "endYear": (e["endDate"] or {}).get("year"),
                "description": e["description"],
            }
        )

    # Certifications and Languages render as plain <li>s under an <h3>, not entity lockups.
    certifications = []
    for item in buckets.get("certifications", []) or _items_under_heading(
        soup, "certifications", "licenses & certifications", "licenses and certifications"
    ):
        e = _parse_entity(item)
        if e["title"]:
            certifications.append(
                {
                    "name": e["title"],
                    "authority": e["subtitle"],
                    "startDate": e["startDate"],
                    "endDate": e["endDate"],
                }
            )

    languages = []
    for item in buckets.get("languages", []) or _items_under_heading(soup, "languages"):
        e = _parse_entity(item)
        if e["title"]:
            languages.append({"name": e["title"], "proficiency": e["subtitle"]})

    skills = []
    seen_skills: set[str] = set()
    for item in soup.select(".skill-item"):
        for hidden in item.select(".sr-only"):
            hidden.decompose()
        heading = item.select_one(".list-item-heading") or item
        name = _clean(heading.get_text(" ", strip=True))
        if name and name not in seen_skills:
            seen_skills.add(name)
            skills.append({"name": name, "endorsementCount": None})

    return {
        "publicIdentifier": public_identifier,
        "profileUrl": profile_url,
        "firstName": first_name,
        "lastName": last_name,
        "fullName": full_name,
        "headline": headline,
        "location": location,
        "currentCompany": current_company,
        "about": about,
        "profileImages": _profile_images(soup),
        "experience": experience,
        "education": education,
        "skills": skills,
        "certifications": certifications,
        "languages": languages,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }
