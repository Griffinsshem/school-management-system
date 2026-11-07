"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { goToLogin } from "@/components/app-shell";
import {
  ErrorMessage,
  dangerButtonClass,
  inlineButtonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
} from "@/components/ui";
import {
  MAX_CANCEL_REASON,
  MAX_PAID_BY,
  MAX_REFERENCE,
  MPESA_CODE,
  PAYMENT_METHODS,
  billPath,
  describeFeesError,
  formatDate,
  formatDayOf,
  formatKes,
  formatReceiptNumber,
  methodLabel,
  parseAmount,
  receiptPath,
  termLabel,
  type Bill,
  type Payment,
  type PaymentMethod,
} from "@/lib/fees";
import { api } from "@/lib/api";
import { isDate, kenyaToday } from "@/lib/attendance";
import { useUnsavedChanges } from "@/lib/unsaved-changes";

import { amountClass, tdClass, thClass } from "../../fees";

// A bill's payments (E2): the list with receipt links, recording a payment
// (school administrators and finance officers) and cancelling one with a
// reason (school administrators only). Payments are never edited: a
// mistake is cancelled and recorded again.

export function Payments({
  bill,
  onChanged,
}: {
  bill: Bill;
  onChanged: (next: Bill, message: string, receipt?: Payment) => void;
}) {
  return (
    <section aria-labelledby="payments-heading" className="mb-8 max-w-3xl">
      <h2 id="payments-heading" className="mb-3 text-xl font-semibold">
        Payments
      </h2>
      {bill.payments.length === 0 ? (
        <p className="mb-4 text-sm">No payments recorded yet.</p>
      ) : (
        <div className="mb-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Payments on this bill</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>
                  Receipt
                </th>
                <th scope="col" className={thClass}>
                  Paid on, how
                </th>
                <th scope="col" className={`${thClass} ${amountClass}`}>
                  Amount
                </th>
                <th scope="col" className={thClass}>
                  Recorded
                </th>
              </tr>
            </thead>
            <tbody>
              {bill.payments.map((payment) => (
                <PaymentRow key={payment.id} bill={bill} payment={payment} onChanged={onChanged} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {bill.can_record_payments && <RecordPayment bill={bill} onChanged={onChanged} />}
    </section>
  );
}

function PaymentRow({
  bill,
  payment,
  onChanged,
}: {
  bill: Bill;
  payment: Payment;
  onChanged: (next: Bill, message: string) => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const number = formatReceiptNumber(payment.receipt_number);
  const cancelled = payment.cancelled;
  return (
    <>
      <tr className={cancelled ? "text-muted" : undefined}>
        <th scope="row" className={`${tdClass} font-normal whitespace-nowrap`}>
          <Link
            href={receiptPath(payment.id)}
            className="text-link underline underline-offset-2"
            aria-label={`Receipt ${number}`}
          >
            {number}
          </Link>
        </th>
        <td className={`${tdClass} break-words`}>
          {formatDate(payment.paid_on)}, {methodLabel(payment.method)}
          {payment.reference && <span className="block">{payment.reference}</span>}
          {payment.paid_by && <span className="block">Paid by {payment.paid_by}</span>}
        </td>
        <td className={`${tdClass} ${amountClass}`}>{formatKes(payment.amount_kes)}</td>
        <td className={`${tdClass} break-words`}>
          {payment.recorded_at && formatDayOf(payment.recorded_at)}
          {payment.recorded_by && `, ${payment.recorded_by}`}
          {cancelled ? (
            <span className="mt-1 block font-semibold text-danger-ink">
              Cancelled: {cancelled.reason}
              <span className="block font-normal">
                {cancelled.cancelled_at && formatDayOf(cancelled.cancelled_at)}
                {cancelled.cancelled_by && `, ${cancelled.cancelled_by}`}
              </span>
            </span>
          ) : (
            bill.can_cancel_payments &&
            !cancelling && (
              <button
                type="button"
                className={`${secondaryButtonClass} mt-2 block py-1 text-sm`}
                aria-label={`Cancel payment ${number}`}
                onClick={() => setCancelling(true)}
              >
                Cancel payment
              </button>
            )
          )}
        </td>
      </tr>
      {cancelling && (
        <tr>
          <td colSpan={4} className={tdClass}>
            <CancelPayment
              bill={bill}
              payment={payment}
              onDone={(next) => {
                setCancelling(false);
                if (next) {
                  onChanged(next, `Payment ${number} cancelled. It stays on the bill, marked cancelled.`);
                }
              }}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function CancelPayment({
  bill,
  payment,
  onDone,
}: {
  bill: Bill;
  payment: Payment;
  onDone: (next: Bill | null) => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const reasonRef = useRef<HTMLInputElement>(null);
  const number = formatReceiptNumber(payment.receipt_number);
  useEffect(() => {
    reasonRef.current?.focus();
  }, []);
  useUnsavedChanges(reason.trim() !== "", () => setReason(""));

  async function cancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!reason.trim()) {
      setError("Enter the reason for cancelling.");
      return;
    }
    setPending(true);
    const response = await api<Bill>(`/school/fees/payments/${payment.id}/cancellation`, {
      method: "POST",
      body: { reason: reason.trim() },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(billPath(bill.id));
    } else if (response.ok) {
      setReason("");
      onDone(response.data);
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={cancel} noValidate aria-label={`Cancel payment ${number}`}>
      <ErrorMessage message={error} />
      <p className="mb-2 font-semibold">
        Cancel payment {number} of {formatKes(payment.amount_kes)}? It stays on the bill, marked cancelled, and
        its receipt number is not used again.
      </p>
      <label htmlFor={`cancel-reason-${payment.id}`} className={labelClass}>
        Reason
      </label>
      <input
        id={`cancel-reason-${payment.id}`}
        ref={reasonRef}
        className={`${inputClass} mb-3`}
        maxLength={MAX_CANCEL_REASON}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={dangerButtonClass} disabled={pending}>
          {pending ? "Cancelling..." : "Yes, cancel payment"}
        </button>
        <button
          type="button"
          className={`${secondaryButtonClass} py-1`}
          disabled={pending}
          onClick={() => {
            setReason("");
            onDone(null);
          }}
        >
          Keep it
        </button>
      </div>
    </form>
  );
}

function RecordPayment({
  bill,
  onChanged,
}: {
  bill: Bill;
  onChanged: (next: Bill, message: string, receipt?: Payment) => void;
}) {
  const today = kenyaToday();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("mpesa");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(today);
  const [paidBy, setPaidBy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const referenceLabel = PAYMENT_METHODS.find((m) => m.value === method)?.reference ?? null;

  function clear() {
    setAmount("");
    setReference("");
    setPaidOn(kenyaToday());
    setPaidBy("");
  }
  useUnsavedChanges(amount.trim() !== "" || reference.trim() !== "" || paidBy.trim() !== "", clear);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const value = parseAmount(amount);
    const code = reference.trim().toUpperCase();
    const problems: string[] = [];
    if (typeof value === "string") {
      problems.push(value);
    }
    if (method === "mpesa" && !MPESA_CODE.test(code)) {
      problems.push(
        "Enter the M-Pesa transaction code from the payment message: 10 letters and digits, for example SJK3ABCD12.",
      );
    } else if ((method === "bank" || method === "cheque") && !reference.trim()) {
      problems.push(`Enter the ${referenceLabel?.toLowerCase()}.`);
    }
    if (!isDate(paidOn)) {
      problems.push("Enter the date the money was paid.");
    } else if (paidOn > today) {
      problems.push("The date paid cannot be in the future.");
    }
    if (problems.length > 0 || typeof value === "string") {
      setError(problems.join(" "));
      return;
    }
    setPending(true);
    const response = await api<{ payment: Payment; bill: Bill }>(`/school/fees/bills/${bill.id}/payments`, {
      method: "POST",
      body: {
        amount_kes: value,
        method,
        reference: method === "cash" ? null : method === "mpesa" ? code : reference.trim(),
        paid_on: paidOn,
        paid_by: paidBy.trim() || null,
      },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(billPath(bill.id));
    } else if (response.ok) {
      clear();
      const { payment } = response.data;
      onChanged(
        response.data.bill,
        `Payment of ${formatKes(payment.amount_kes)} recorded: receipt ${formatReceiptNumber(payment.receipt_number)}.`,
        payment,
      );
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={save} noValidate aria-labelledby="record-heading" className="rounded-lg border border-rule p-4">
      <h3 id="record-heading" className="mb-3 text-lg font-semibold">
        Record a payment
      </h3>
      <EarlierOwed bill={bill} />
      <ErrorMessage message={error} />
      <div className="grid gap-x-4 sm:grid-cols-2">
        <div>
          <label htmlFor="payment-amount" className={labelClass}>
            Amount received (KES)
          </label>
          <input
            id="payment-amount"
            className={`${inputClass} mb-3`}
            inputMode="numeric"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="payment-method" className={labelClass}>
            How it was paid
          </label>
          <select
            id="payment-method"
            className={`${inputClass} mb-3`}
            value={method}
            onChange={(event) => {
              setMethod(event.target.value as PaymentMethod);
              setReference("");
            }}
          >
            {PAYMENT_METHODS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        {referenceLabel && (
          <div>
            <label htmlFor="payment-reference" className={labelClass}>
              {referenceLabel}
            </label>
            {method === "mpesa" && (
              <p id="payment-reference-hint" className="mb-1 text-sm text-muted">
                10 letters and digits from the payment message, for example SJK3ABCD12.
              </p>
            )}
            <input
              id="payment-reference"
              className={`${inputClass} mb-3 ${method === "mpesa" ? "uppercase" : ""}`}
              aria-describedby={method === "mpesa" ? "payment-reference-hint" : undefined}
              autoComplete="off"
              spellCheck={false}
              maxLength={method === "mpesa" ? 10 : MAX_REFERENCE}
              value={reference}
              onChange={(event) => setReference(event.target.value)}
            />
          </div>
        )}
        <div>
          <label htmlFor="payment-date" className={labelClass}>
            Date paid
          </label>
          <input
            id="payment-date"
            type="date"
            className={`${inputClass} mb-3`}
            max={today}
            value={paidOn}
            onChange={(event) => setPaidOn(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="payment-payer" className={labelClass}>
            Payer&apos;s name (optional)
          </label>
          <input
            id="payment-payer"
            className={`${inputClass} mb-3`}
            maxLength={MAX_PAID_BY}
            autoComplete="off"
            value={paidBy}
            onChange={(event) => setPaidBy(event.target.value)}
          />
        </div>
      </div>
      <button type="submit" className={inlineButtonClass} disabled={pending}>
        {pending ? "Recording..." : "Record payment"}
      </button>
    </form>
  );
}

// E3: earlier terms still owed, so money meant for them can be recorded on
// their bill instead (nothing is moved automatically).
function EarlierOwed({ bill }: { bill: Bill }) {
  const owed = bill.earlier.bills.filter((earlier) => earlier.balance_kes > 0);
  if (owed.length === 0) {
    return null;
  }
  const total = owed.reduce((sum, earlier) => sum + earlier.balance_kes, 0);
  return (
    <div role="note" className="mb-3 rounded-md border-l-4 border-rule-strong px-3 py-2 text-sm">
      <p>
        {bill.student.full_name} also owes {formatKes(total)} from earlier terms. If the family means this payment
        for an earlier term, record it on that bill:
      </p>
      <ul className="list-disc pl-5">
        {owed.map((earlier) => (
          <li key={earlier.id}>
            <Link
              href={billPath(earlier.id)}
              className="text-link underline underline-offset-2"
              aria-label={`Record on the ${termLabel(earlier.term, earlier.year)} bill`}
            >
              {termLabel(earlier.term, earlier.year)}
            </Link>
            : {formatKes(earlier.balance_kes)} owed
          </li>
        ))}
      </ul>
    </div>
  );
}
