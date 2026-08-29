import type {
  CertificationEntry,
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  LinkedInProfile,
  ProfileImage,
  SkillEntry,
} from "./types";

// Bump whenever parsing logic changes so cached/stored records can be traced back to the parser
// version that produced them, and so reparse() results are distinguishable from live ones.
export const PARSER_VERSION = 1;

// LinkedIn's voyager responses are a flat "included" array of typed entities (Profile, Position,
// Education, Skill, ...) rather than one nested object. This shape is undocumented and has shifted
// across LinkedIn releases before — see README "Known limitations".
interface VoyagerEntity {
  $type?: string;
  entityUrn?: string;
  [key: string]: unknown;
}

interface VoyagerResponse {
  included?: VoyagerEntity[];
}

function entitiesOfType(response: VoyagerResponse, typeSuffix: string): VoyagerEntity[] {
  return (response.included ?? []).filter((entity) => entity.$type?.endsWith(typeSuffix));
}

function firstEntityOfType(response: VoyagerResponse, typeSuffix: string): VoyagerEntity | undefined {
  return entitiesOfType(response, typeSuffix)[0];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function parseDate(value: unknown): { month: number | null; year: number | null } | null {
  if (!value || typeof value !== "object") return null;
  const date = value as { month?: number; year?: number };
  if (date.month === undefined && date.year === undefined) return null;
  return { month: date.month ?? null, year: date.year ?? null };
}

function parseTimePeriod(entity: VoyagerEntity): {
  startDate: { month: number | null; year: number | null } | null;
  endDate: { month: number | null; year: number | null } | null;
} {
  const timePeriod = entity.timePeriod as { startDate?: unknown; endDate?: unknown } | undefined;
  return {
    startDate: parseDate(timePeriod?.startDate),
    endDate: parseDate(timePeriod?.endDate),
  };
}

function parseProfileImages(profile: VoyagerEntity | undefined): ProfileImage[] {
  const displayImageReference = (profile as { profilePicture?: { displayImageReference?: unknown } } | undefined)
    ?.profilePicture?.displayImageReference as
    | { vectorImage?: { rootUrl?: string; artifacts?: Array<{ width?: number; height?: number; fileIdentifyingUrlPathSegment?: string }> } }
    | undefined;

  const vectorImage = displayImageReference?.vectorImage;
  if (!vectorImage?.rootUrl || !vectorImage.artifacts) return [];

  return vectorImage.artifacts
    .filter((artifact) => artifact.fileIdentifyingUrlPathSegment)
    .map((artifact) => ({
      url: `${vectorImage.rootUrl}${artifact.fileIdentifyingUrlPathSegment}`,
      width: artifact.width,
      height: artifact.height,
    }));
}

function parseExperience(response: VoyagerResponse): ExperienceEntry[] {
  return entitiesOfType(response, "Position").map((position) => {
    const { startDate, endDate } = parseTimePeriod(position);
    return {
      title: asString(position.title),
      companyName: asString(position.companyName),
      location: asString(position.locationName),
      description: asString(position.description),
      startDate,
      endDate,
      isCurrent: endDate === null && startDate !== null,
    };
  });
}

function parseEducation(response: VoyagerResponse): EducationEntry[] {
  return entitiesOfType(response, "Education").map((education) => {
    const { startDate, endDate } = parseTimePeriod(education);
    return {
      schoolName: asString(education.schoolName),
      degreeName: asString(education.degreeName),
      fieldOfStudy: asString(education.fieldOfStudy),
      startYear: startDate?.year ?? null,
      endYear: endDate?.year ?? null,
      description: asString(education.description),
    };
  });
}

function parseSkills(response: VoyagerResponse): SkillEntry[] {
  return entitiesOfType(response, "Skill")
    .map((skill) => ({
      name: asString(skill.name) ?? "",
      endorsementCount: asNumber(skill.endorsementCount),
    }))
    .filter((skill) => skill.name.length > 0);
}

function parseCertifications(response: VoyagerResponse): CertificationEntry[] {
  return entitiesOfType(response, "Certification").map((cert) => {
    const { startDate, endDate } = parseTimePeriod(cert);
    return {
      name: asString(cert.name) ?? "",
      authority: asString(cert.authority),
      startDate,
      endDate,
    };
  });
}

function parseLanguages(response: VoyagerResponse): LanguageEntry[] {
  return entitiesOfType(response, "Language").map((language) => ({
    name: asString(language.name) ?? "",
    proficiency: asString(language.proficiency),
  }));
}

export function parseProfileView(raw: unknown, publicIdentifier: string, profileUrl: string): LinkedInProfile {
  const response = raw as VoyagerResponse;
  const profile = firstEntityOfType(response, "identity.profile.Profile");

  const firstName = asString(profile?.firstName);
  const lastName = asString(profile?.lastName);

  return {
    publicIdentifier,
    profileUrl,
    firstName,
    lastName,
    fullName: firstName || lastName ? [firstName, lastName].filter(Boolean).join(" ") : null,
    headline: asString(profile?.headline),
    location: asString(profile?.geoLocationName) ?? asString(profile?.locationName),
    about: asString(profile?.summary),
    profileImages: parseProfileImages(profile),
    experience: parseExperience(response),
    education: parseEducation(response),
    skills: parseSkills(response),
    certifications: parseCertifications(response),
    languages: parseLanguages(response),
    fetchedAt: new Date().toISOString(),
  };
}
