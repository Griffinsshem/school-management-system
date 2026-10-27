// School years and terms as the API returns them (see backend/README.md).

export type Term = {
  number: number;
  name: string; // "Term 1"
  starts_on: string; // "YYYY-MM-DD"
  ends_on: string;
};

export type AcademicYear = {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
  terms: Term[]; // In number order; a term not set yet is missing.
};

// Worked out by the API in Kenyan time, so every visitor sees the same day.
export type Today = {
  today: string;
  academic_year_id: string | null;
  term_number: number | null;
  next_term: { academic_year_id: string; number: number; starts_on: string } | null;
};

export type AcademicYearList = {
  academic_years: AcademicYear[]; // Newest first.
  current: Today;
};

export const TERM_NUMBERS = [1, 2, 3];
export const MAX_YEAR_NAME = 20;
// The API accepts dates in these years only.
export const EARLIEST_DATE = "2000-01-01";
export const LATEST_DATE = "2100-12-31";

// Term and year dates are calendar dates, not moments in time: format them
// without any time-zone conversion, so they never shift by a day.
export function formatCalendarDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { dateStyle: "medium" });
}

// One sentence saying where today falls: in a term, in a holiday, or
// outside every school year.
export function describeToday(list: AcademicYearList): string {
  const { current, academic_years: years } = list;
  if (years.length === 0) {
    return "No school years yet.";
  }
  const yearName = (id: string) => years.find((year) => year.id === id)?.name ?? "";
  const today = formatCalendarDate(current.today);
  const next = current.next_term
    ? ` Term ${current.next_term.number} of ${yearName(current.next_term.academic_year_id)} starts on ${formatCalendarDate(current.next_term.starts_on)}.`
    : "";

  if (current.academic_year_id && current.term_number) {
    return `Today, ${today}, is in Term ${current.term_number} of ${yearName(current.academic_year_id)}.`;
  }
  if (current.academic_year_id) {
    return next
      ? `Today, ${today}, is a school holiday.${next}`
      : `Today, ${today}, is in ${yearName(current.academic_year_id)}, outside any term.`;
  }
  return `No school year covers today, ${today}.${next}`;
}
