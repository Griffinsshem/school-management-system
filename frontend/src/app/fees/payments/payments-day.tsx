"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { formatDay, isDate, kenyaToday } from "@/lib/attendance";
import {
  billPath,
  canSeeFees,
  formatDate,
  formatKes,
  formatReceiptNumber,
  methodLabel,
  paymentsDayPath,
  receiptPath,
  type DayPayments,
} from "@/lib/fees";

import { NoFeesAccess, amountClass, tdClass, thClass } from "../fees";

// Every payment recorded on one day (E2), with totals by method, so the
// bursar can check the cash drawer and the M-Pesa statement before banking.
// Cancelled payments are listed but not counted.

export function PaymentsDayPage() {
  const asked = useSearchParams().get("date");
  const date = isDate(asked) ? asked : kenyaToday();
  return <AppShell path="/fees">{(me) => <Content me={me} date={date} />}</AppShell>;
}

function Content({ me, date }: { me: Me; date: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Payments on a day" />;
  }
  return <DayView key={`${school.id}/${date}`} date={date} />;
}

function DayView({ date }: { date: string }) {
  const router = useRouter();
  const today = kenyaToday();
  const [day, setDay] = useState<DayPayments | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dayText, setDayText] = useState(date);

  useEffect(() => {
    let cancelled = false;
    api<DayPayments>(`/school/fees/payments?${new URLSearchParams({ date })}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(paymentsDayPath(date === today ? undefined : date));
      } else if (response.ok) {
        setDay(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [date, today]);

  function showDay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isDate(dayText)) {
      router.push(paymentsDayPath(dayText));
    }
  }

  return (
    <>
      <p className="mb-2">
        <Link href="/fees" className="text-sm text-link underline underline-offset-2">
          Back to fees
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-[1.9375rem] leading-tight font-bold tracking-tight">Payments on a day</h1>
          <p className="text-muted">Recorded on {formatDay(date)}</p>
        </div>
        <form onSubmit={showDay} className="flex flex-wrap items-end gap-2" noValidate>
          <div>
            <label htmlFor="day" className={labelClass}>
              Day
            </label>
            <input
              id="day"
              type="date"
              className={inputClass}
              max={today}
              value={dayText}
              onChange={(event) => setDayText(event.target.value)}
            />
          </div>
          <button type="submit" className={secondaryButtonClass}>
            Show
          </button>
        </form>
      </div>

      <ErrorMessage message={error} />

      {!day ? (
        !error && <p className="text-muted">Loading...</p>
      ) : (
        <>
          <section aria-labelledby="totals-heading" className="mb-8 max-w-sm">
            <h2 id="totals-heading" className="mb-3 text-xl font-semibold">
              Totals
            </h2>
            <table className="w-full border-collapse text-left">
              <caption className="sr-only">Totals by how it was paid</caption>
              <tbody>
                {day.totals.map((total) => (
                  <tr key={total.method}>
                    <th scope="row" className={`${tdClass} font-normal`}>
                      {total.name}
                    </th>
                    <td className={`${tdClass} ${amountClass}`}>{formatKes(total.amount_kes)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row" className="px-2 py-2 font-semibold">
                    All payments
                  </th>
                  <td className={`px-2 py-2 font-semibold ${amountClass}`}>{formatKes(day.total_kes)}</td>
                </tr>
              </tfoot>
            </table>
            {day.cancelled > 0 && (
              <p className="mt-2 text-sm text-muted">
                {day.cancelled} cancelled payment{day.cancelled === 1 ? " is" : "s are"} listed below but not
                counted.
              </p>
            )}
          </section>

          <section aria-labelledby="list-heading" className="max-w-4xl">
            <h2 id="list-heading" className="mb-3 text-xl font-semibold">
              Payments
            </h2>
            {day.payments.length === 0 ? (
              <p>No payments were recorded on this day.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-sm">
                  <caption className="sr-only">Payments recorded on {formatDay(date)}</caption>
                  <thead>
                    <tr>
                      <th scope="col" className={thClass}>
                        Receipt
                      </th>
                      <th scope="col" className={thClass}>
                        Student
                      </th>
                      <th scope="col" className={thClass}>
                        How, paid on
                      </th>
                      <th scope="col" className={`${thClass} ${amountClass}`}>
                        Amount
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {day.payments.map((payment) => {
                      const number = formatReceiptNumber(payment.receipt_number);
                      return (
                        <tr key={payment.id} className={payment.cancelled ? "text-muted" : undefined}>
                          <th scope="row" className={`${tdClass} font-normal whitespace-nowrap`}>
                            <Link
                              href={receiptPath(payment.id)}
                              className="text-link underline underline-offset-2"
                              aria-label={`Receipt ${number}`}
                            >
                              {number}
                            </Link>
                            {payment.cancelled && (
                              <span className="block font-semibold text-danger-ink">Cancelled</span>
                            )}
                          </th>
                          <td className={`${tdClass} break-words`}>
                            <Link
                              href={billPath(payment.bill_id)}
                              className="text-link underline underline-offset-2"
                              aria-label={`${payment.student.full_name}'s bill`}
                            >
                              {payment.student.full_name}
                            </Link>
                            <span className="block">{payment.class_name}</span>
                          </td>
                          <td className={`${tdClass} break-words`}>
                            {methodLabel(payment.method)}
                            {payment.reference && <span className="block">{payment.reference}</span>}
                            <span className="block">{formatDate(payment.paid_on)}</span>
                          </td>
                          <td className={`${tdClass} ${amountClass}`}>{formatKes(payment.amount_kes)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
