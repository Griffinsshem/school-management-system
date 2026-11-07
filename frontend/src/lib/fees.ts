import type { ApiErrorBody, Me } from "@/lib/api";
import { withReference } from "@/lib/api";

// School fees as the API returns them (E1, see backend/app/api/v1/fees.py).
// Amounts are whole Kenyan shillings.

export const MAX_FEE_ITEMS = 30;
export const MAX_FEE_ITEM_NAME = 60;
export const MAX_ADJUSTMENT_REASON = 200;
export const MAX_FEE_AMOUNT = 1_000_000;
// Payments (E2, see backend/app/models/payments.py).
export const MAX_REFERENCE = 40;
export const MAX_PAID_BY = 100;
export const MAX_CANCEL_REASON = 200;
export const MPESA_CODE = /^[A-Z0-9]{10}$/;

export type PaymentMethod = "cash" | "mpesa" | "bank" | "cheque";

export const PAYMENT_METHODS: { value: PaymentMethod; label: string; reference: string | null }[] = [
  { value: "mpesa", label: "M-Pesa", reference: "M-Pesa transaction code" },
  { value: "cash", label: "Cash", reference: null },
  { value: "bank", label: "Bank deposit or transfer", reference: "Bank reference" },
  { value: "cheque", label: "Cheque", reference: "Cheque number" },
];

export function methodLabel(method: PaymentMethod): string {
  return PAYMENT_METHODS.find((m) => m.value === method)?.label ?? method;
}

// What a bill (or a row of bills) says about money: a balance below 0
// means the family paid more than was owed.
type Money = { total_kes: number; paid_kes: number; balance_kes: number };

export type Payment = {
  id: string;
  receipt_number: number;
  amount_kes: number;
  method: PaymentMethod;
  reference: string | null;
  paid_on: string;
  paid_by: string | null;
  recorded_at: string | null;
  recorded_by: string | null;
  cancelled: { reason: string; cancelled_at: string | null; cancelled_by: string | null } | null;
};

type StudentRef = { id: string; full_name: string; admission_number: string };

// The student's bills from earlier terms (E3): their balance added together
// (below 0 is a credit) and those not settled. Worked out by the API each
// time, never stored.
export type Earlier = {
  balance_kes: number;
  bills: { id: string; term: { number: number }; year: { name: string }; balance_kes: number }[];
};

type WithEarlier = { earlier: Earlier; due_now_kes: number };

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
  billed_kes: number;
  paid_kes: number;
  outstanding_kes: number;
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
  bills: ({ id: string; student: StudentRef; class_name: string } & Money)[];
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
  school: { name: string };
  student: StudentRef;
  class_name: string;
  grade: { code: string; name: string };
  issued_at: string | null;
  issued_by: string | null;
  lines: BillLine[];
  payments: Payment[];
  optional_items: { id: string; name: string; amount_kes: number }[];
  guardians: {
    full_name: string;
    relationship: string;
    is_primary: boolean;
    phone: string;
    email: string | null;
  }[];
  can_manage: boolean;
  can_record_payments: boolean;
  can_cancel_payments: boolean;
} & Money &
  WithEarlier;

// A bill as printed (E3): one, or a whole grade's for a term.
export type PrintedBill = {
  id: string;
  student: StudentRef;
  class_name: string;
  lines: { kind: "fee" | "adjustment"; description: string; amount_kes: number }[];
} & Money &
  WithEarlier;

export type GradeBillsToPrint = TermRef & {
  school: { name: string };
  grade: { code: string; name: string };
  bills: PrintedBill[];
};

// A student's fee statement (E3): every charge, payment and cancellation in
// date order with a running balance. A debit adds to what is owed, a
// credit takes it off.
export type StatementEntry = {
  date: string;
  kind: "fee" | "adjustment" | "payment" | "cancellation";
  description: string;
  bill_id: string;
  term: { number: number };
  year: { name: string };
  debit_kes: number | null;
  credit_kes: number | null;
  balance_kes: number;
  payment: { id: string; receipt_number: number; method: PaymentMethod; reference: string | null } | null;
};

export type Statement = {
  school: { name: string };
  student: StudentRef;
  class_name: string | null;
  printed_on: string;
  entries: StatementEntry[];
  totals: { charged_kes: number; paid_kes: number; balance_kes: number };
};

export type Receipt = {
  payment: Payment;
  school: { name: string };
  bill: TermRef & { id: string; student: StudentRef; class_name: string; grade: { code: string; name: string } };
  balance_after_kes: number;
};

export type DayPayments = {
  date: string;
  payments: (Payment & { bill_id: string; student: StudentRef; class_name: string })[];
  totals: { method: PaymentMethod; name: string; amount_kes: number }[];
  total_kes: number;
  cancelled: number;
};

export type StudentBills = {
  student: StudentRef;
  bills: ({ id: string; term: { id: string; number: number }; year: { name: string }; class_name: string } & Money)[];
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

export function billPrintPath(id: string): string {
  return `/fees/bills/${id}/print`;
}

export function gradeBillsPrintPath(yearId: string, term: number, grade: string): string {
  return `${gradeFeesPath(yearId, term, grade)}/print`;
}

export function statementPath(studentId: string): string {
  return `/fees/students/${studentId}/statement`;
}

// "Term 3, 2026".
export function termLabel(term: { number: number }, year: { name: string }): string {
  return `Term ${term.number}, ${year.name}`;
}

export function receiptPath(paymentId: string): string {
  return `/fees/receipts/${paymentId}`;
}

export function paymentsDayPath(day?: string): string {
  return day ? `/fees/payments?${new URLSearchParams({ date: day })}` : "/fees/payments";
}

// Receipt numbers are shown with six digits: Receipt No. 000012.
export function formatReceiptNumber(n: number): string {
  return String(n).padStart(6, "0");
}

// "KES 7,000 still owed", "Fully paid", "Overpaid by KES 500 (credit)".
export function describeBalance(balance: number): string {
  if (balance > 0) {
    return `${formatKes(balance)} still owed`;
  }
  if (balance < 0) {
    return `Overpaid by ${formatKes(-balance)} (credit)`;
  }
  return "Fully paid";
}

// A balance in a table cell: "KES 7,000", or "KES 500 credit" when overpaid.
export function formatBalance(balance: number): string {
  return balance < 0 ? `${formatKes(-balance)} credit` : formatKes(balance);
}

// A calendar date (2027-02-09) as people read it: 9 Feb 2027.
export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
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
