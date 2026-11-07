import { formatBalance, formatKes, termLabel, type Earlier, type PrintedBill, type TermRef } from "@/lib/fees";

import { amountClass, tdClass, thClass } from "./fees";

// One bill as it goes home on paper (E3): the school, the student, the
// term's fees, what is paid, the balance from earlier terms and the amount
// due now. Used for one bill and for a whole grade's bills, one per page.

export function PrintedBillView({
  school,
  term,
  year,
  bill,
  className = "",
}: { school: { name: string }; bill: PrintedBill } & TermRef & { className?: string }) {
  const label = termLabel(term, year);
  const hasEarlier = bill.earlier.balance_kes !== 0 || bill.earlier.bills.length > 0;
  return (
    <article
      aria-label={`Bill for ${bill.student.full_name}`}
      className={`max-w-xl min-w-0 rounded-lg border border-rule-strong p-4 break-words sm:p-6 print:max-w-none print:rounded-none print:border-0 print:p-0 ${className}`}
    >
      <header className="mb-4 border-b border-rule-strong pb-3">
        <p className="text-xl font-bold">{school.name}</p>
        <p className="text-muted">School fees bill, {label}</p>
      </header>

      <dl className="mb-4 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[auto_minmax(0,1fr)] [&>dd]:mb-2 sm:[&>dd]:mb-0">
        <dt className="text-muted">Student</dt>
        <dd className="font-semibold">
          {bill.student.full_name}
          <span className="block font-normal">Admission no. {bill.student.admission_number}</span>
        </dd>
        <dt className="text-muted">Class</dt>
        <dd>{bill.class_name}</dd>
      </dl>

      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Fees for {label}</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>
              Item
            </th>
            <th scope="col" className={`${thClass} ${amountClass}`}>
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {bill.lines.length === 0 && (
            <tr>
              <td colSpan={2} className={tdClass}>
                No fees on this bill.
              </td>
            </tr>
          )}
          {bill.lines.map((line, n) => (
            <tr key={n}>
              <th scope="row" className={`${tdClass} font-normal break-words`}>
                {line.kind === "adjustment" ? `Adjustment: ${line.description}` : line.description}
              </th>
              <td className={`${tdClass} ${amountClass}`}>{formatKes(line.amount_kes)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <MoneyRow label={`Total for ${label}`} value={formatKes(bill.total_kes)} strong />
          <MoneyRow label="Paid" value={formatKes(bill.paid_kes)} />
          <MoneyRow label={`Balance for ${label}`} value={formatBalance(bill.balance_kes)} />
          {hasEarlier && <MoneyRow label="From earlier terms" value={formatBalance(bill.earlier.balance_kes)} />}
          <MoneyRow label="Amount due now" value={formatBalance(bill.due_now_kes)} strong />
        </tfoot>
      </table>

      {bill.earlier.bills.length > 0 && <EarlierTerms earlier={bill.earlier} />}
      {bill.due_now_kes < 0 && (
        <p className="mt-3 text-sm">Nothing is due: the family has a credit of {formatKes(-bill.due_now_kes)}.</p>
      )}
    </article>
  );
}

function MoneyRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  const weight = strong ? "text-base font-semibold" : "font-normal";
  return (
    <tr>
      <th scope="row" className={`px-2 py-1 ${weight}`}>
        {label}
      </th>
      <td className={`px-2 py-1 ${amountClass} ${weight}`}>{value}</td>
    </tr>
  );
}

// The earlier terms behind "From earlier terms", as text (a printed page
// has no links).
export function EarlierTerms({ earlier }: { earlier: Earlier }) {
  return (
    <div className="mt-3 text-sm">
      <p className="text-muted">From earlier terms:</p>
      <ul className="list-disc pl-5">
        {earlier.bills.map((bill) => (
          <li key={bill.id}>
            {termLabel(bill.term, bill.year)}: {formatBalance(bill.balance_kes)}
            {bill.balance_kes > 0 ? " owed" : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
