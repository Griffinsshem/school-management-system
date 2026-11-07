"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import {
  canSeeFees,
  describeBalance,
  formatBalance,
  formatDate,
  formatKes,
  formatReceiptNumber,
  methodLabel,
  receiptPath,
  statementPath,
  termLabel,
  type Statement,
  type StatementEntry,
} from "@/lib/fees";

import { NoFeesAccess, amountClass, tdClass, thClass } from "../../../fees";

// A student's fee statement (E3), ready to print or save as a PDF for the
// family: every charge, payment and cancellation across all terms, in date
// order, with a running balance. No guardian contacts: it goes home on paper.

export function StatementPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/fees">{(me) => <Content me={me} studentId={id} />}</AppShell>;
}

function Content({ me, studentId }: { me: Me; studentId: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Fee statement" />;
  }
  return <StatementView key={school.id} studentId={studentId} />;
}

function StatementView({ studentId }: { studentId: string }) {
  const [statement, setStatement] = useState<Statement | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Statement>(`/school/fees/students/${studentId}/statement`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(statementPath(studentId));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setStatement(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [studentId]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Student not found</h1>
        <p>
          This student does not exist, or is not in this school.{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!statement) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  const { student, totals } = statement;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link href="/fees" className="text-sm text-link underline underline-offset-2">
              Back to fees
            </Link>
          </p>
          <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight break-words">
            Fee statement for {student.full_name}
          </h1>
        </div>
        <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
          Print
        </button>
      </div>

      <article
        aria-label={`Fee statement for ${student.full_name}`}
        className="max-w-4xl min-w-0 rounded-lg border border-rule-strong p-4 break-words sm:p-6 print:max-w-none print:rounded-none print:border-0 print:p-0"
      >
        <header className="mb-4 border-b border-rule-strong pb-3">
          <p className="text-xl font-bold">{statement.school.name}</p>
          <p className="text-muted">School fees statement, printed on {formatDate(statement.printed_on)}</p>
        </header>

        <dl className="mb-4 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[auto_minmax(0,1fr)] [&>dd]:mb-2 sm:[&>dd]:mb-0">
          <dt className="text-muted">Student</dt>
          <dd className="font-semibold">
            {student.full_name}
            <span className="block font-normal">Admission no. {student.admission_number}</span>
          </dd>
          {statement.class_name && (
            <>
              <dt className="text-muted">Class</dt>
              <dd>{statement.class_name}</dd>
            </>
          )}
          <dt className="text-muted">Balance</dt>
          <dd className="font-semibold">{describeBalance(totals.balance_kes)}</dd>
        </dl>

        {statement.entries.length === 0 ? (
          <p>No bills have been issued to {student.full_name} yet.</p>
        ) : (
          <>
            {/* Phones: one small block per line, so every amount is in view.
                Wider screens and paper: the table. */}
            <ol aria-label="Charges and payments, oldest first" className="divide-y divide-rule border-y border-rule text-sm sm:hidden print:hidden">
              {statement.entries.map((entry, n) => (
                <li key={n} className="py-2">
                  <p className="text-muted">{formatDate(entry.date)}</p>
                  <p className="break-words">
                    <Details entry={entry} />
                  </p>
                  <p className="mt-1 flex flex-wrap justify-between gap-x-3">
                    <span>
                      {entry.debit_kes !== null
                        ? `Charged ${formatKes(entry.debit_kes)}`
                        : `Paid or taken off ${formatKes(entry.credit_kes ?? 0)}`}
                    </span>
                    <span className="font-semibold whitespace-nowrap">Balance {formatBalance(entry.balance_kes)}</span>
                  </p>
                </li>
              ))}
            </ol>
            <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 text-sm font-semibold sm:hidden print:hidden [&>dd]:text-right">
              <dt>Total charged</dt>
              <dd>{formatKes(totals.charged_kes)}</dd>
              <dt>Total paid</dt>
              <dd>{formatKes(totals.paid_kes)}</dd>
              <dt>Balance</dt>
              <dd>{formatBalance(totals.balance_kes)}</dd>
            </dl>
            <div className="hidden overflow-x-auto sm:block print:block print:overflow-visible">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">Charges and payments, oldest first</caption>
                <thead>
                  <tr>
                    <th scope="col" className={thClass}>
                      Date
                    </th>
                    <th scope="col" className={thClass}>
                      Details
                    </th>
                    <th scope="col" className={`${thClass} ${amountClass}`}>
                      Charged
                    </th>
                    <th scope="col" className={`${thClass} ${amountClass}`}>
                      Paid or taken off
                    </th>
                    <th scope="col" className={`${thClass} ${amountClass}`}>
                      Balance
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {statement.entries.map((entry, n) => (
                    <tr key={n}>
                      <td className={`${tdClass} whitespace-nowrap`}>{formatDate(entry.date)}</td>
                      <th scope="row" className={`${tdClass} min-w-40 font-normal break-words`}>
                        <Details entry={entry} />
                      </th>
                      <td className={`${tdClass} ${amountClass}`}>
                        {entry.debit_kes !== null && formatKes(entry.debit_kes)}
                      </td>
                      <td className={`${tdClass} ${amountClass}`}>
                        {entry.credit_kes !== null && formatKes(entry.credit_kes)}
                      </td>
                      <td className={`${tdClass} ${amountClass}`}>{formatBalance(entry.balance_kes)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={2} className="px-2 py-2 font-semibold">
                      Totals
                    </th>
                    <td className={`px-2 py-2 font-semibold ${amountClass}`}>{formatKes(totals.charged_kes)}</td>
                    <td className={`px-2 py-2 font-semibold ${amountClass}`}>{formatKes(totals.paid_kes)}</td>
                    <td className={`px-2 py-2 font-semibold ${amountClass}`}>{formatBalance(totals.balance_kes)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </>
        )}
        <p className="mt-4 border-t border-rule pt-3 text-sm text-muted">
          &quot;Charged&quot; includes adjustments that add to a bill; &quot;Paid or taken off&quot; includes
          bursaries and other reductions. A cancelled payment is listed as paid and then added back.
        </p>
      </article>
    </>
  );
}

function Details({ entry }: { entry: StatementEntry }) {
  const term = termLabel(entry.term, entry.year);
  const payment = entry.payment;
  if (payment) {
    const number = formatReceiptNumber(payment.receipt_number);
    const receipt = (
      <Link href={receiptPath(payment.id)} className="text-link underline underline-offset-2 print:text-ink print:no-underline">
        receipt {number}
      </Link>
    );
    if (entry.kind === "cancellation") {
      return (
        <>
          Payment cancelled ({receipt}): {entry.description}
          <span className="block text-muted">{term}</span>
        </>
      );
    }
    return (
      <>
        Payment, {receipt}, {methodLabel(payment.method)}
        {payment.reference && ` ${payment.reference}`}
        <span className="block text-muted">{term}</span>
      </>
    );
  }
  return (
    <>
      {entry.kind === "adjustment" ? `Adjustment: ${entry.description}` : entry.description}
      <span className="block text-muted">{term}</span>
    </>
  );
}
