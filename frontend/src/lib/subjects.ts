// Subjects, the subjects each class takes, and their teachers, as the API
// returns them (see backend/README.md).

import type { Me } from "@/lib/api";

export type Subject = {
  id: string;
  name: string;
  code: string | null;
  // An inactive subject stays on the classes that already take it, but
  // cannot be added to more.
  is_active: boolean;
};

export type SubjectTeacher = {
  membership_id: string;
  full_name: string;
  // False once the person is no longer an active teacher of the school.
  is_active: boolean;
};

export type ClassSubject = { subject: Subject; teachers: SubjectTeacher[] };

export type ClassSubjects = {
  class: { id: string; academic_year_id: string; name: string };
  subjects: ClassSubject[];
};

export const MAX_SUBJECT_NAME = 60;
export const MAX_SUBJECT_CODE = 10;

export function canReadSubjects(me: Me): boolean {
  return me.permissions.includes("subjects.read");
}

export function canManageSubjects(me: Me): boolean {
  return me.permissions.includes("subjects.manage");
}
