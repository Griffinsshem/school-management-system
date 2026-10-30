// A class's term results (D6), as the API returns them (see backend/README.md).

import type { ClassRef, AssessmentTerm } from "@/lib/assessments";
import type { Scale, TermResult } from "@/lib/grading";
import type { KcseCategory } from "@/lib/subjects";

export type Overall = {
  total_points: number;
  subjects_counted: number;
  mean_points: number;
  grade: string;
  // False without Mathematics or a language, or with fewer subjects than
  // counted (KCSE: seven); CBC: without a result in every assessed subject.
  complete: boolean;
};

export type ResultStudent = {
  id: string;
  admission_number: string;
  full_name: string;
  in_class: boolean;
  results: Record<string, TermResult>; // By subject ID.
  overall: Overall | null;
  position?: number | null; // Only when the school shows positions.
};

export type ClassResults = {
  class: ClassRef;
  term: AssessmentTerm;
  scale: Scale;
  show_positions: boolean;
  subjects: {
    id: string;
    name: string;
    code: string | null;
    kcse_category: KcseCategory;
    weighted: boolean;
    weight_total: number;
  }[];
  students: ResultStudent[];
};

export function classResultsPath(classId: string, term?: number): string {
  const base = `/classes/${classId}/results`;
  return term ? `${base}?${new URLSearchParams({ term: String(term) })}` : base;
}
