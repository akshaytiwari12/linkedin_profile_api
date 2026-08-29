export interface ProfileImage {
  url: string;
  width?: number;
  height?: number;
}

export interface ExperienceEntry {
  title: string | null;
  companyName: string | null;
  location: string | null;
  description: string | null;
  startDate: { month: number | null; year: number | null } | null;
  endDate: { month: number | null; year: number | null } | null;
  isCurrent: boolean;
}

export interface EducationEntry {
  schoolName: string | null;
  degreeName: string | null;
  fieldOfStudy: string | null;
  startYear: number | null;
  endYear: number | null;
  description: string | null;
}

export interface SkillEntry {
  name: string;
  endorsementCount: number | null;
}

export interface CertificationEntry {
  name: string;
  authority: string | null;
  startDate: { month: number | null; year: number | null } | null;
  endDate: { month: number | null; year: number | null } | null;
}

export interface LanguageEntry {
  name: string;
  proficiency: string | null;
}

export interface LinkedInProfile {
  publicIdentifier: string;
  profileUrl: string;
  firstName: string | null;
  lastName: string | null;
  fullName: string | null;
  headline: string | null;
  location: string | null;
  about: string | null;
  profileImages: ProfileImage[];
  experience: ExperienceEntry[];
  education: EducationEntry[];
  skills: SkillEntry[];
  certifications: CertificationEntry[];
  languages: LanguageEntry[];
  fetchedAt: string;
}

export interface RawPayloadRecord {
  id: string;
  publicIdentifier: string;
  fetchedAt: string;
  raw: unknown;
}

export interface CachedProfileRecord {
  publicIdentifier: string;
  profile: LinkedInProfile;
  parserVersion: number;
  rawPayloadId: string;
  cachedAt: string;
  expiresAt: string;
}

export type JobStatus = "queued" | "processing" | "completed" | "failed";

export interface JobRecord {
  id: string;
  publicIdentifier: string;
  profileUrl: string;
  status: JobStatus;
  result?: LinkedInProfile;
  error?: string;
  createdAt: string;
  updatedAt: string;
}

export type SessionState = "healthy" | "flagged";

export interface SessionHealthRecord {
  state: SessionState;
  consecutiveFailures: number;
  lastError: string | null;
  lastErrorAt: string | null;
  flaggedAt: string | null;
  lastRequestAt: string | null;
}
