"""Regression tests for the HTML parser, using synthetic markup that mirrors the two real
top-card orderings observed on live profiles.

The headline/location assignment was twice mis-assigned during development because the top card
does not order those lines consistently — these tests pin both observed orderings so a future
change cannot silently reintroduce it.

Run:  python3 -m tests.test_html_parser
"""

import sys

from app.html_parser import parse_profile_html

# Ordering A: headline directly under the name, then company, then connection count.
# The About block is long and comma-bearing — it must never be mistaken for the headline.
TOPCARD_A = """
<html><body>
  <h1 class="heading-large">Jane Doe</h1>
  <div class="body-small text-color-text"><span>Principal Engineer - VP of Cloud Infrastructure</span></div>
  <div class="body-small text-color-text-low-emphasis"><span class="member-current-company">Example Systems</span></div>
  <div class="body-small text-color-text-low-emphasis"><span class="whitespace-nowrap">500+ connections</span></div>
  <div class="truncated-summary"><div class="whitespace-pre-line description">I lead a platform team, working across reliability,
       cost, and developer experience, with a focus on distributed systems.</div></div>
  <h2>Experience</h2>
  <ul><li class="profile-entity-lockup">
    <span class="list-item-heading">Principal Engineer</span>
    <span>Example Systems</span>
    <span>Jan 2024 -</span><span>Present</span><span>2 yrs 8 mos</span>
    <span>Bengaluru, Karnataka, India</span>
  </li></ul>
</body></html>
"""

# Ordering B: a short line precedes the real headline, and the location carries commas.
TOPCARD_B = """
<html><body>
  <h1 class="heading-large">Sam Roe</h1>
  <div class="badges"><span class="sr-only">Content writer</span></div>
  <div class="body-small text-color-text"><span>QA Engineer @XY || Manual and - Automation | SomeQA Certified | Freelancer</span></div>
  <div class="body-small text-color-text-low-emphasis"><span>East District in Somecity , Region</span></div>
  <div class="body-small text-color-text-low-emphasis"><span class="member-current-company">XY</span></div>
  <div class="body-small text-color-text-low-emphasis"><span class="whitespace-nowrap">500+ connections</span></div>
  <h2>Experience</h2>
  <ul><li class="profile-entity-lockup">
    <span class="list-item-heading">QA Engineer</span>
    <span>Some Corp</span>
    <span>Mar 2021 -</span><span>Jun 2023</span><span>2 yrs 3 mos</span>
  </li></ul>
  <h2>Education</h2>
  <ul><li class="entity-lockup profile-entity-lockup">
    <span class="list-item-heading">Example University</span>
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


def test_ordering_a() -> None:
    print("Top card ordering A (headline first):")
    p = parse_profile_html(TOPCARD_A, "jane-doe", "https://www.linkedin.com/in/jane-doe/")
    check("fullName", p["fullName"], "Jane Doe")
    check("firstName", p["firstName"], "Jane")
    check("headline", p["headline"], "Principal Engineer - VP of Cloud Infrastructure")
    check("location is null when absent", p["location"], None)
    check("company not mistaken for location", p["currentCompany"], "Example Systems")
    check("about is the long block", p["about"].startswith("I lead a platform team"), True)
    check("headline is not the about text", len(p["headline"]) < 100, True)
    check("experience count", len(p["experience"]), 1)
    check("experience title", p["experience"][0]["title"], "Principal Engineer")
    check("experience start", p["experience"][0]["startDate"], {"month": 1, "year": 2024})
    check("experience isCurrent", p["experience"][0]["isCurrent"], True)
    check("experience location", p["experience"][0]["location"], "Bengaluru, Karnataka, India")


def test_ordering_b() -> None:
    print("\nTop card ordering B (short line before headline):")
    p = parse_profile_html(TOPCARD_B, "sam-roe", "https://www.linkedin.com/in/sam-roe/")
    check("fullName", p["fullName"], "Sam Roe")
    check(
        "headline picks the long tagline",
        p["headline"],
        "QA Engineer @XY || Manual and - Automation | SomeQA Certified | Freelancer",
    )
    check("location", p["location"], "East District in Somecity , Region")
    check("currentCompany", p["currentCompany"], "XY")
    check("sr-only badge ignored", p["headline"].startswith("QA Engineer"), True)
    check("experience end date", p["experience"][0]["endDate"], {"month": 6, "year": 2023})
    check("experience not current", p["experience"][0]["isCurrent"], False)
    check("education count", len(p["education"]), 1)
    check("education school", p["education"][0]["schoolName"], "Example University")
    check("education years", (p["education"][0]["startYear"], p["education"][0]["endYear"]), (2008, 2010))


def test_noise_is_excluded() -> None:
    print("\nTop-card noise handling:")
    p = parse_profile_html(TOPCARD_B, "sam-roe", "u")
    for field in ("headline", "location"):
        value = (p.get(field) or "").lower()
        check(f"{field} is not a connection count", "connections" in value, False)
        check(f"{field} is not a degree badge", value.strip() in ("2nd", "1st"), False)


def test_empty_and_partial() -> None:
    print("\nDegrades cleanly on missing sections:")
    p = parse_profile_html("<html><body><h1>Nobody</h1></body></html>", "nobody", "u")
    check("fullName", p["fullName"], "Nobody")
    check("experience", p["experience"], [])
    check("education", p["education"], [])
    check("skills", p["skills"], [])
    check("languages", p["languages"], [])
    check("about", p["about"], None)


if __name__ == "__main__":
    test_ordering_a()
    test_ordering_b()
    test_noise_is_excluded()
    test_empty_and_partial()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        sys.exit(1)
    print("All HTML parser tests passed.")
