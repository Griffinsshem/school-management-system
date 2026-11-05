import type { ApiErrorBody, Me } from "@/lib/api";
import { withReference } from "@/lib/api";

// School fees as the API returns them (E1, see backend/app/api/v1/fees.py).
// Amounts are whole Kenyan shillings.

export const MAX_FEE_ITEMS = 30;
export const MAX_FEE_ITEM_NAME = 60;
export const MAX_ADJUSTMENT_REASON = 200;
export const MAX_FEE_AMOUNT = 1_000_000;

type StudentRef = { id: string; full_name: string; admission_number: string };

export type TermRef = {
  term: { id: string; number: number; starts_on: string; ends_on: string };
  year: { id: string; name: string };
};

export type GradeRow = {
  grade: string;
  name: string;
  classes: number;
  students: number;
  billed: number;
  structure: { items: number; compulsory_total_kes: number; issued: boolean } | null;
};

export type TermFees = TermRef & { can_manage: boolean; grades: GradeRow[] };

export type FeeItem = { id: string; name: string; amount_kes: number; is_optional: boolean };

export type Structure = {
  id: string;
  items: FeeItem[];
  compulsory_total_kes: number;
  issued_at: string | null;
  issued_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

export type GradeFees = TermRef & {
  grade: { code: string; name: string };
  can_manage: boolean;
  structure: Structure | null;
  bills: { id: string; student: StudentRef; class_name: string; total_kes: number }[];
  not_billed: { student: StudentRef; class_name: string }[];
};

export type IssueResult = GradeFees & { billed: number };

export type BillLine = {
  id: string;
  kind: "fee" | "adjustment";
  description: string;
  amount_kes: number;
  created_at: string | null;
  created_by: string | null;
};

export type Bill = TermRef & {
  id: string;
  student: StudentRef;
  class_name: string;
  grade: { code: string; name: string };
  issued_at: string | null;
  issued_by: string | null;
  lines: BillLine[];
  total_kes: number;
  optional_items: { id: string; name: string; amount_kes: number }[];
  guardians: {
    full_name: string;
    relationship: string;
    is_primary: boolean;
    phone: string;
    email: string | null;
  }[];
  can_manage: boolean;
};

export type StudentBills = {
  student: StudentRef;
  bills: { id: string; term: { id: string; number: number }; year: { name: string }; class_name: string; total_kes: number }[];
};

export function canSeeFees(me: Me): boolean {
  return me.permissions.includes("fees.read");
}

export function feesPath(yearId?: string, term?: number): string {
  if (!yearId || !term) {
    return "/fees";
  }
  return `/fees?${new URLSearchParams({ year: yearId, term: String(term) })}`;
}

export function gradeFeesPath(yearId: string, term: number, grade: string): string {
  return `/fees/${yearId}/${term}/${grade}`;
}

export function billPath(id: string): string {
  return `/fees/bills/${id}`;
}

// The day of a moment (when bills were issued, a line added), in Kenya.
export function formatDayOf(moment: string): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "Africa/Nairobi" }).format(
    new Date(moment),
  );
}

// "KES 15,000"; negative amounts start with a minus sign: "-KES 5,000".
export function formatKes(amount: number): string {
  const sign = amount < 0 ? "-" : "";
  return `${sign}KES ${Math.abs(amount).toLocaleString("en-KE")}`;
}

// A typed amount in whole shillings ("15000", "15,000", "-5 000"), or a
// message saying what is wrong. The server checks again.
export function parseAmount(
  text: string,
  { allowNegative = false }: { allowNegative?: boolean } = {},
): number | string {
  const cleaned = text.replace(/[\s,]/g, "");
  if (cleaned === "") {
    return "Enter an amount.";
  }
  if (!/^-?\d+$/.test(cleaned)) {
    return "Enter a whole number of shillings, without cents.";
  }
  const value = Number(cleaned);
  if (value < 0 && !allowNegative) {
    return "Enter an amount above 0.";
  }
  if (value === 0) {
    return allowNegative ? "An adjustment cannot be 0." : "Enter an amount above 0.";
  }
  if (Math.abs(value) > MAX_FEE_AMOUNT) {
    return `An amount can be at most ${formatKes(MAX_FEE_AMOUNT)}.`;
  }
  return value;
}

// The API's messages, made readable.
export function describeFeesError(status: number, error: ApiErrorBody): string {
  if (status === 409 || status === 404 || status === 403) {
    return error.message;
  }
  if (status === 422) {
    if (error.details && error.details.length > 0) {
      return error.details.map((d) => d.message.replace(/^Value error, /, "")).join(" ");
    }
    return error.message;
  }
  return withReference(error);
}
