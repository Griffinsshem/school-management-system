"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import {
  billPath,
  canSeeFees,
  describeBalance,
  formatDate,
  formatDayOf,
  formatKes,
  formatReceiptNumber,
  methodLabel,
  receiptPath,
  type Receipt,
} from "@/lib/fees";

import { NoFeesAccess } from "../../fees";

// A payment's receipt (E2), ready to print or save as a PDF from the
// browser's print dialog. The balance is the bill's balance just after this
// payment, so a receipt printed again later shows the same figures.

export function ReceiptPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/fees">{(me) => <Content me={me} paymentId={id} />}</AppShell>;
}

function Content({ me, paymentId }: { me: Me; paymentId: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Receipt" />;
  }
  return <ReceiptView key={school.id} paymentId={paymentId} />;
}

function ReceiptView({ paymentId }: { paymentId: string }) {
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Receipt>(`/school/fees/payments/${paymentId}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(receiptPath(paymentId));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setReceipt(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [paymentId]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Receipt not found</h1>
        <p>
          This receipt does not exist, or it is not in this school.{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!receipt) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  const { payment, bill } = receipt;
  const number = formatReceiptNumber(payment.receipt_number);
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link href={billPath(bill.id)} className="text-sm text-link underline underline-offset-2">
              Back to {bill.student.full_name}&apos;s bill
            </Link>
          </p>
          <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight">Receipt {number}</h1>
        </div>
        <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
          Print
        </button>
      </div>

      <article
        aria-label={`Receipt ${number}`}
        className="max-w-xl min-w-0 rounded-lg border border-rule-strong p-4 break-words sm:p-6 print:max-w-none print:rounded-none print:border-0 print:p-0"
      >
        <header className="mb-4 border-b border-rule-strong pb-3">
          <p className="text-xl font-bold">{receipt.school.name}</p>
          <p className="text-muted">School fees receipt</p>
          <p className="mt-2 text-lg font-semibold">Receipt No. {number}</p>
        </header>

        {payment.cancelled && (
          <div role="note" className="mb-4 rounded-md border-l-4 border-danger bg-danger-soft px-3 py-2 text-danger-ink">
            <p className="text-lg font-bold">CANCELLED</p>
            <p>Reason: {payment.cancelled.reason}</p>
            <p className="text-sm">
              {payment.cancelled.cancelled_at && formatDayOf(payment.cancelled.cancelled_at)}
              {payment.cancelled.cancelled_by && `, ${payment.cancelled.cancelled_by}`}
            </p>
          </div>
        )}

        {/* One column on phones. The second column may shrink below its
            longest word (minmax(0, ...)), so a long payer's name or reference
            wraps (break-words, from the article) instead of widening the page. */}
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[auto_minmax(0,1fr)] sm:gap-y-2 [&>dd]:mb-2 sm:[&>dd]:mb-0">
          <dt className="text-muted">Student</dt>
          <dd className="font-semibold">
            {bill.student.full_name}
            <span className="block font-normal">Admission no. {bill.student.admission_number}</span>
          </dd>
          <dt className="text-muted">Class</dt>
          <dd>{bill.class_name}</dd>
          <dt className="text-muted">For</dt>
          <dd>
            Term {bill.term.number} fees, {bill.year.name}
          </dd>
          <dt className="text-muted">Amount</dt>
          <dd className="text-xl font-bold whitespace-nowrap">{formatKes(payment.amount_kes)}</dd>
          <dt className="text-muted">Paid by</dt>
          <dd>
            {methodLabel(payment.method)}
            {payment.reference && `, ${payment.reference}`}
          </dd>
          <dt className="text-muted">Date paid</dt>
          <dd>{formatDate(payment.paid_on)}</dd>
          {payment.paid_by && (
            <>
              <dt className="text-muted">Received from</dt>
              <dd>{payment.paid_by}</dd>
            </>
          )}
          <dt className="text-muted">Balance after this payment</dt>
          <dd className="font-semibold">{describeBalance(receipt.balance_after_kes)}</dd>
        </dl>

        <p className="mt-4 border-t border-rule pt-3 text-sm text-muted">
          Recorded {payment.recorded_at && `on ${formatDayOf(payment.recorded_at)}`}
          {payment.recorded_by && ` by ${payment.recorded_by}`}.
        </p>
      </article>
    </>
  );
}
