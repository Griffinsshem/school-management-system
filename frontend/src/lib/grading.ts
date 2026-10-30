// Grading scales and grades (D5). The API works grades out and sends them;
// this file only repeats its rule to show a grade while a score is typed:
// the percentage is rounded to a whole number (halves up), then the first
// band whose minimum it reaches is the grade (see backend/app/grading.py).

import type { Me } from "@/lib/api";

export type Band = { grade: string; min_percent: number; points: number };
export type Scale = { kind: "cbc" | "kcse"; bands: Band[] };
export type Result = { percent: number; grade: string; points: number };
// `weighted` (D6): the percentage counts each assessment by its weight, so
// `score` / `max_score` are only the raw totals.
export type TermResult = Result & { score: number; max_score: number; weighted: boolean };

export type Grading = {
  cbc: Scale;
  kcse: Scale & { is_default: boolean };
  default_kcse: Record<string, number>;
  show_class_positions: boolean; // D6
};

export const SCALE_NAMES: Record<Scale["kind"], string> = {
  cbc: "CBC (KJSEA) scale",
  kcse: "KCSE scale",
};

export function canManageGrading(me: Me): boolean {
  return me.permissions.includes("grading.manage");
}

export function wholePercent(score: number, max: number): number {
  // Scores have at most one decimal place: working in tenths keeps the
  // division exact at the halves, so they round up as on the server.
  return Math.floor((Math.round(score * 10) * 100) / (max * 10) + 0.5);
}

export function gradeFor(score: number, max: number, scale: Scale): Result {
  const percent = wholePercent(score, max);
  const band = scale.bands.find((b) => percent >= b.min_percent) ?? scale.bands[scale.bands.length - 1];
  return { percent, grade: band.grade, points: band.points };
}

// "80% A": how a grade is shown next to a score being typed.
export function formatResult(result: Result): string {
  return `${result.percent}% ${result.grade}`;
}
