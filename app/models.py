"""Response models.

These exist for the generated OpenAPI docs as much as for validation: without them every
endpoint documents its response as an untyped object, which makes `/docs` far less useful to
anyone trying to understand the API before calling it.

Every field is optional. A LinkedIn profile may omit any section, and the API reports that
honestly as `null`/`[]` rather than inventing a value — so the schema has to allow it.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DateParts(BaseModel):
    """A partial date. LinkedIn often publishes only a year, so `month` may be null."""

    month: int | None = Field(None, ge=1, le=12, examples=[1])
    year: int | None = Field(None, examples=[2024])


class ProfileImage(BaseModel):
    url: str = Field(examples=["https://media.licdn.com/dms/image/v2/..."])
    width: int | None = None
    height: int | None = None


class ExperienceEntry(BaseModel):
    """One position. LinkedIn groups roles by employer, so several entries can share a
    `companyName` — a promotion within one company yields one entry per role."""

    title: str | None = Field(None, examples=["Principal Engineer"])
    companyName: str | None = Field(None, examples=["Example Systems"])
    location: str | None = Field(None, examples=["Bengaluru, Karnataka, India"])
    description: str | None = Field(
        None,
        description="May be truncated: LinkedIn renders only the collapsed portion of long text.",
        examples=["Led the platform team across reliability and developer experience."],
    )
    startDate: DateParts | None = None
    endDate: DateParts | None = Field(
        None, description="Null when the role is current — see `isCurrent`."
    )
    isCurrent: bool = Field(False, examples=[True])


class EducationEntry(BaseModel):
    schoolName: str | None = Field(None, examples=["Example University"])
    degreeName: str | None = Field(None, examples=["BE - Bachelor of Engineering"])
    fieldOfStudy: str | None = Field(None, examples=["Information Technology"])
    startYear: int | None = Field(None, examples=[2015])
    endYear: int | None = Field(None, examples=[2019])
    description: str | None = None


class SkillEntry(BaseModel):
    name: str = Field(examples=["Distributed Systems"])
    endorsementCount: int | None = Field(
        None, description="Always null — endorsement counts are not rendered on this surface."
    )


class CertificationEntry(BaseModel):
    name: str | None = Field(None, examples=["AWS Certified Developer"])
    authority: str | None = Field(
        None, description="Always null — the issuer is rendered inline with the name."
    )
    startDate: DateParts | None = None
    endDate: DateParts | None = None


class LanguageEntry(BaseModel):
    name: str = Field(examples=["English"])
    proficiency: str | None = Field(None, examples=["Native or bilingual"])


class LinkedInProfile(BaseModel):
    publicIdentifier: str = Field(
        description="The slug from the profile URL.", examples=["jane-doe-1a2b3c"]
    )
    profileUrl: str = Field(examples=["https://www.linkedin.com/in/jane-doe-1a2b3c/"])
    firstName: str | None = Field(None, examples=["Jane"])
    lastName: str | None = Field(None, examples=["Doe"])
    fullName: str | None = Field(None, examples=["Jane Doe"])
    headline: str | None = Field(
        None, examples=["Principal Engineer | Platform & Reliability | Distributed Systems"]
    )
    location: str | None = Field(None, examples=["Bengaluru, Karnataka, India"])
    currentCompany: str | None = Field(None, examples=["Example Systems"])
    about: str | None = Field(
        None,
        description="May be truncated to the portion LinkedIn renders before its 'see more' control.",
    )
    profileImages: list[ProfileImage] = []
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    skills: list[SkillEntry] = []
    certifications: list[CertificationEntry] = []
    languages: list[LanguageEntry] = []
    fetchedAt: str = Field(
        description="When the underlying page was fetched (ISO 8601, UTC).",
        examples=["2026-08-31T09:14:02+00:00"],
    )
    source: Literal["live", "cache", "reparsed"] | None = Field(
        None,
        description=(
            "`live` — just fetched from LinkedIn. "
            "`cache` — served from the result cache, no LinkedIn request. "
            "`reparsed` — re-parsed from stored HTML, no LinkedIn request."
        ),
    )
    cachedAt: str | None = Field(None, description="Present only when `source` is `cache`.")
    expiresAt: str | None = Field(None, description="Present only when `source` is `cache`.")


class JobAccepted(BaseModel):
    """Returned when a fetch is still running past the long-poll window."""

    jobId: str = Field(examples=["3f9a1c74-9c2e-4f2a-9c1b-2f9f0a1d7e55"])
    status: Literal["queued", "processing"] = Field(examples=["processing"])
    statusUrl: str = Field(examples=["/api/jobs/3f9a1c74-9c2e-4f2a-9c1b-2f9f0a1d7e55"])


class JobStatus(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed"]
    result: LinkedInProfile | None = Field(None, description="Present only when `completed`.")
    error: str | None = Field(None, description="Present only when `failed`.")
    updatedAt: str | None = None


class SessionHealth(BaseModel):
    """State of the LinkedIn session and its circuit breaker."""

    state: Literal["healthy", "flagged"] = Field(
        description="`flagged` means the breaker is open and no requests will be sent."
    )
    consecutiveFailures: int = 0
    lastError: str | None = None
    lastErrorAt: str | None = None
    flaggedAt: str | None = None
    lastRequestAt: str | None = None


class ErrorResponse(BaseModel):
    error: str = Field(examples=["LinkedIn session is invalid or expired."])
    jobId: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ResetResponse(BaseModel):
    status: Literal["reset"] = "reset"
