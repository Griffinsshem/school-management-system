// Report cards and class teachers' comments (D7), as the API returns them
// (see backend/README.md). Everything but the comment is worked out from
// marks and registers each time, with the same numbers as the results page.

import type { ClassResults, ResultStudent } from "@/lib/results";

export const MAX_COMMENT_LENGTH = 500;

export type Attendance = { present: number; late: number; absent: number; days_recorded: number };

export type ReportComment = { text: string; updated_at: string; updated_by: string };

export type ReportCard = ResultStudent & { attendance: Attendance; comment: ReportComment | null };

type ClassPart = Omit<ClassResults, "students"> & {
  school: { name: string };
  year: { name: string };
  can_comment: boolean;
  position_out_of?: number; // Only when the school shows positions.
};

export type ClassReportCards = ClassPart & { students: ReportCard[] };
export type OneReportCard = ClassPart & { student: ReportCard };

function withTerm(path: string, term?: number): string {
  return term ? `${path}?${new URLSearchParams({ term: String(term) })}` : path;
}

export function reportCardsPath(classId: string, term?: number): string {
  return withTerm(`/classes/${classId}/report-cards`, term);
}

export function reportCardPath(classId: string, studentId: string, term?: number): string {
  return withTerm(`/classes/${classId}/report-cards/${studentId}`, term);
}

export function printReportCardsPath(classId: string, term?: number): string {
  return withTerm(`/classes/${classId}/report-cards/print`, term);
}

// The problem with a comment before it is sent, as the API words it, or null.
// An empty comment clears it; one of only spaces is refused.
export function commentProblem(text: string): string | null {
  const trimmed = text.replace(/\r\n?/g, "\n").trim();
  if (text !== "" && trimmed === "") {
    return "A comment cannot be only spaces. Leave it empty to clear it.";
  }
  if (trimmed.length > MAX_COMMENT_LENGTH) {
    return `A comment can be at most ${MAX_COMMENT_LENGTH} characters (this one has ${trimmed.length}).`;
  }
  return null;
}
