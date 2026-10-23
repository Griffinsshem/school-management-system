// Student records as the API returns them (see backend/README.md).

export type Student = {
  id: string;
  admission_number: string;
  full_name: string;
  date_of_birth: string | null; // "YYYY-MM-DD"
  is_active: boolean;
};

export type StudentPage = {
  students: Student[];
  page: number;
  per_page: number;
  total: number;
};

export type StudentFields = {
  admission_number: string;
  full_name: string;
  date_of_birth: string; // "" when not given
};

export const PER_PAGE = 50;
export const MAX_ADMISSION_NUMBER = 30;
export const MAX_NAME = 200;
export const MAX_SEARCH = 100;

// A date of birth is a calendar date, not a moment in time: format it without
// any time-zone conversion, so it never shifts by a day.
export function formatBirthDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function isoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

// The date picker's limits, in the browser's own time zone. The API checks
// the same rules (no future dates, at most 30 years ago).
export const MAX_AGE_YEARS = 30;

export function todayIso(): string {
  return isoDate(new Date());
}

export function oldestBirthDateIso(): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() - MAX_AGE_YEARS);
  return isoDate(date);
}
