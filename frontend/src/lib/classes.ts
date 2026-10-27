// Classes and class teachers as the API returns them (see backend/README.md).

import type { AcademicYearList } from "@/lib/academic-years";

export type ClassTeacher = {
  membership_id: string;
  full_name: string;
  // False once the person is no longer an active teacher of the school.
  is_active: boolean;
};

export type SchoolClass = {
  id: string;
  academic_year_id: string;
  grade: string; // A code such as "grade_4"
  grade_name: string; // "Grade 4"
  stream: string | null;
  name: string; // "Grade 4 East"
  teachers: ClassTeacher[];
};

export type Grade = { code: string; name: string };

export type ClassList = {
  academic_year: { id: string; name: string };
  grades: Grade[]; // Only the grades that exist in this school year.
  classes: SchoolClass[];
};

export const MAX_STREAM = 20;

// The year to show first: the one containing today, else the one with the
// next term, else the newest.
export function defaultYearId(list: AcademicYearList): string | null {
  const { current, academic_years: years } = list;
  return current.academic_year_id ?? current.next_term?.academic_year_id ?? years[0]?.id ?? null;
}
