// Attendance registers as the API returns them (see backend/README.md).

import type { Me } from "@/lib/api";

// Who may open the attendance pages: readers of every class, and teachers
// of their own classes.
export function canSeeAttendance(me: Me): boolean {
  return me.permissions.includes("attendance.read") || me.permissions.includes("attendance.record_own");
}

export type Status = "present" | "absent" | "late";
export type Reason = "sick" | "permission" | "unknown";

export const STATUSES: { value: Status; label: string }[] = [
  { value: "present", label: "Present" },
  { value: "absent", label: "Absent" },
  { value: "late", label: "Late" },
];

// The only reasons the API accepts (no free text about children).
export const REASONS: { value: Reason; label: string }[] = [
  { value: "sick", label: "Sick" },
  { value: "permission", label: "With permission" },
  { value: "unknown", label: "Unknown" },
];

export type RegisterStudent = { id: string; admission_number: string; full_name: string };

export type Mark = { student: RegisterStudent; status: Status; reason: Reason | null };

export type Register = {
  class: { id: string; academic_year_id: string; name: string };
  date: string; // "YYYY-MM-DD"
  term_number: number | null;
  taken: boolean;
  taken_by: string | null;
  taken_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
  // Whether the logged-in user may save this register.
  editable: boolean;
  // For a class teacher: the last day they may change it.
  teacher_can_change_until: string | null;
  // A register not taken yet lists the class's active students as present.
  marks: Mark[];
};

export type Counts = {
  present: number;
  absent: number;
  late: number;
  absent_by_reason: Record<Reason, number>;
};

export type TermSummary = {
  class: { id: string; academic_year_id: string; name: string };
  term: { number: number; starts_on: string; ends_on: string };
  registers: ({ date: string } & Counts)[];
  students: ({ student: RegisterStudent; in_class: boolean } & Counts)[];
};

export type Overview = {
  date: string;
  academic_year_id: string | null;
  term_number: number | null;
  classes: ({ class: { id: string; academic_year_id: string; name: string }; taken: boolean } & Counts)[];
};

// Today's date in Kenya, as the API counts days.
export function kenyaToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
}

export function isDate(value: string | null): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

// "Wednesday, 10 February 2027", without any time-zone shift.
export function formatDay(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { dateStyle: "full" });
}

export function registerPath(classId: string, date: string): string {
  return `/classes/${classId}/attendance?${new URLSearchParams({ date })}`;
}

export function reasonLabel(reason: Reason | null): string {
  return REASONS.find((r) => r.value === reason)?.label ?? "";
}
