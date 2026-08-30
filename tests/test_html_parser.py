"""Regression tests for the HTML parser, using synthetic markup that mirrors the real mwlite
top card and entity lockups.

Both fields these tests pin were mis-assigned during development, more than once:

  * headline/location were picked by text length and position, which silently returned the
    About text as the headline on one profile and the headline as the location on another;
  * experience title/company were inverted on every entry, because a lockup's heading is the
    *company* and roles are nested inside it — and every role after the first was dropped.

Field counts looked correct throughout, which is why these assert values.

Run:  python3 -m tests.test_html_parser
"""

import sys

from app.html_parser import parse_profile_html

# Real top card layout: a container whose direct children are name, headline, school/company,
# then the location row with the connection count appended.
TOPCARD_A = """
<html><body>
 <div class="bg-color-background-container mx-2 mt-2 mb-1">
  <div class="flex items-center"><h1 class="heading-large">Jane Doe</h1></div>
  <div class="body-small text-color-text"><span>Principal Engineer - VP of Cloud Infrastructure</span></div>
  <div class="body-small text-color-text-low-emphasis"><span class="member-current-company">Example Systems</span></div>
  <div class="body-small text-color-text-low-emphasis"><span>Bengaluru, Karnataka, India</span><span class="whitespace-nowrap">500+ connections</span></div>
 </div>
 <h2>About</h2>
 <div class="truncated-summary"><div class="whitespace-pre-line description">I lead a platform team, working across
   reliability, cost, and developer experience. …See more See less</div></div>
 <h2>Experience</h2>
 <ul><li class="profile-entity-lockup grouped">
   <div class="body-medium-bold list-item-heading text-color-text"><span>Example Systems</span></div>
   <div class="self-center"><div class="body-small text-color-text">4 yrs 2 mos</div></div>
   <div class="mr-6 body-small-bold text-color-text"><span>Principal Engineer</span></div>
   <div class="mr-6 body-small text-color-text"><span class="body-small">Jan 2024 -</span><span class="body-small">Present</span><span>2 yrs 8 mos</span></div>
   <div class="text-xs text-color-text-low-emphasis"><span>Bengaluru, Karnataka, India</span></div>
   <div class="mr-6 body-small-bold text-color-text"><span>Staff Engineer</span></div>
   <div class="mr-6 body-small text-color-text"><span class="body-small">Mar 2022 -</span><span class="body-small">Dec 2023</span></div>
 </li></ul>
</body></html>
"""

# A profile whose top card carries a school row instead of a company, and a two-word location.
TOPCARD_B = """
<html><body>
 <div class="bg-color-background-container mx-2 mt-2 mb-1">
  <div class="flex items-center"><h1 class="heading-large">Sam Roe</h1></div>
  <div class="body-small text-color-text"><span>QA Engineer @XY || Manual and - Automation | Freelancer</span></div>
  <div class="body-small text-color-text-low-emphasis"><span>Example University of Technology</span></div>
  <div class="body-small text-color-text-low-emphasis"><span>Kolkata, West Bengal, India</span><span class="whitespace-nowrap">440 connections</span></div>
 </div>
 <h2>Education</h2>
 <ul><li class="entity-lockup profile-entity-lockup">
   <div class="body-medium-bold list-item-heading text-color-text"><span>Example University</span></div>
   <span>BBA</span><span>IT</span>
   <span>2008 -</span><span>2010</span>
 </li></ul>
</body></html>
"""

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        failures.append(label)


def test_top_card() -> None:
    print("Top card:")
    p = parse_profile_html(TOPCARD_A, "jane-doe", "https://www.linkedin.com/in/jane-doe/")
    check("fullName", p["fullName"], "Jane Doe")
    check("firstName", p["firstName"], "Jane")
    check("headline", p["headline"], "Principal Engineer - VP of Cloud Infrastructure")
    check("location strips connection count", p["location"], "Bengaluru, Karnataka, India")
    check("currentCompany", p["currentCompany"], "Example Systems")
    check("headline is not the About text", "platform team" not in (p["headline"] or ""), True)
    check("about strips see more/less", p["about"].endswith("developer experience."), True)


def test_top_card_with_school_row() -> None:
    print("\nTop card whose second row is a school, not a company:")
    p = parse_profile_html(TOPCARD_B, "sam-roe", "https://www.linkedin.com/in/sam-roe/")
    check("headline", p["headline"], "QA Engineer @XY || Manual and - Automation | Freelancer")
    check("school not mistaken for location", p["location"], "Kolkata, West Bengal, India")
    check("education school", p["education"][0]["schoolName"], "Example University")
    check("education degree", p["education"][0]["degreeName"], "BBA")
    check(
        "education years",
        (p["education"][0]["startYear"], p["education"][0]["endYear"]),
        (2008, 2010),
    )


def test_grouped_roles() -> None:
    print("\nGrouped experience (company heading, roles nested):")
    p = parse_profile_html(TOPCARD_A, "jane-doe", "u")
    check("both roles returned", len(p["experience"]), 2)

    first, second = p["experience"][0], p["experience"][1]
    check("role 1 title is the job", first["title"], "Principal Engineer")
    check("role 1 company is the employer", first["companyName"], "Example Systems")
    check("role 1 start", first["startDate"], {"month": 1, "year": 2024})
    check("role 1 isCurrent", first["isCurrent"], True)
    check("role 1 location", first["location"], "Bengaluru, Karnataka, India")

    check("role 2 title", second["title"], "Staff Engineer")
    check("role 2 company", second["companyName"], "Example Systems")
    check("role 2 end", second["endDate"], {"month": 12, "year": 2023})
    check("role 2 not current", second["isCurrent"], False)


def test_empty_and_partial() -> None:
    print("\nDegrades cleanly on missing sections:")
    p = parse_profile_html("<html><body><h1>Nobody</h1></body></html>", "nobody", "u")
    check("fullName", p["fullName"], "Nobody")
    check("headline", p["headline"], None)
    check("location", p["location"], None)
    check("experience", p["experience"], [])
    check("education", p["education"], [])
    check("skills", p["skills"], [])
    check("languages", p["languages"], [])
    check("about", p["about"], None)


if __name__ == "__main__":
    test_top_card()
    test_top_card_with_school_row()
    test_grouped_roles()
    test_empty_and_partial()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        sys.exit(1)
    print("All HTML parser tests passed.")
