// Assessments and marks as the API returns them (see backend/README.md).

import { withReference, type ApiErrorBody, type Me } from "@/lib/api";

export type AssessmentTerm = { number: number; starts_on: string; ends_on: string };

export type Assessment = {
  id: string;
  term: number;
  name: string;
  max_score: number;
  held_on: string; // "YYYY-MM-DD"
  is_locked: boolean;
  marks_entered: number;
};

export type SubjectRef = { id: string; name: string; code: string | null };
export type ClassRef = { id: string; academic_year_id: string; name: string };

export type AssessmentList = {
  class: ClassRef;
  subject: SubjectRef;
  terms: AssessmentTerm[];
  students: number; // In the class now.
  can_record: boolean;
  assessments: Assessment[];
};

export type SheetStudent = {
  id: string;
  admission_number: string;
  full_name: string;
  in_class: boolean; // False for a student who has left but kept a mark.
  score: number | null;
  did_not_sit: boolean;
};

export type MarkSheet = {
  class: ClassRef;
  subject: SubjectRef;
  assessment: Assessment;
  can_record: boolean;
  can_lock: boolean;
  students: SheetStudent[];
};

export type OverviewMark = { score: number | null; did_not_sit: boolean };

export type ClassMarks = {
  class: ClassRef;
  term: AssessmentTerm;
  students: { id: string; admission_number: string; full_name: string; in_class: boolean }[];
  subjects: {
    subject: SubjectRef;
    assessments: (Assessment & { marks: Record<string, OverviewMark> })[];
  }[];
};

export const MAX_ASSESSMENT_NAME = 60;
export const MAX_SCORE_LIMIT = 1000;

// Who may open a class's marks overview: readers of every class, and class
// teachers (the API decides; teachers who are not class teachers get 404).
export function canReadAllMarks(me: Me): boolean {
  return me.permissions.includes("marks.read") || me.permissions.includes("marks.record");
}

export function hasAnyMarksAccess(me: Me): boolean {
  return canReadAllMarks(me) || me.permissions.includes("marks.record_own");
}

export function subjectMarksPath(classId: string, subjectId: string, term?: number): string {
  const base = `/classes/${classId}/subjects/${subjectId}/marks`;
  return term ? `${base}?${new URLSearchParams({ term: String(term) })}` : base;
}

export function classMarksPath(classId: string, term?: number): string {
  const base = `/classes/${classId}/marks`;
  return term ? `${base}?${new URLSearchParams({ term: String(term) })}` : base;
}

// The term to show first: the one containing today, else the last one that
// has started, else the first.
export function defaultTerm(terms: AssessmentTerm[], today: string): number | null {
  const current = terms.find((t) => t.starts_on <= today && today <= t.ends_on);
  const started = terms.filter((t) => t.starts_on <= today);
  return current?.number ?? started[started.length - 1]?.number ?? terms[0]?.number ?? null;
}

// "12", "12.5": a score as people write it. Parsing refuses anything else.
export function formatScore(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

export function percent(score: number, max: number): string {
  return `${Math.round((score / max) * 100)}%`;
}

// A typed score: null when empty, a number with at most one decimal place,
// or an error message.
export function parseScore(text: string, max: number): number | null | { error: string } {
  const value = text.trim();
  if (value === "") {
    return null;
  }
  if (!/^\d+(\.\d)?$/.test(value)) {
    return { error: "Use a number with at most one decimal place, such as 12 or 12.5." };
  }
  const score = Number(value);
  if (score > max) {
    return { error: `The highest score is ${max}.` };
  }
  return score;
}

// The API's messages, made readable (see the students page).
export function describeMarksError(status: number, error: ApiErrorBody): string {
  if (status === 409 || status === 404 || status === 403) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details.map((d) => d.message.replace(/^Value error, /, "")).join(" ");
  }
  return withReference(error);
}
