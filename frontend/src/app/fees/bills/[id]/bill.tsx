"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import {
  MAX_ADJUSTMENT_REASON,
  billPath,
  billPrintPath,
  canSeeFees,
  formatBalance,
  describeFeesError,
  formatDayOf,
  formatKes,
  formatReceiptNumber,
  gradeFeesPath,
  parseAmount,
  receiptPath,
  statementPath,
  termLabel,
  type Bill,
  type Payment,
} from "@/lib/fees";
import { relationshipLabel, type Relationship } from "@/lib/guardians";
import { useUnsavedChanges } from "@/lib/unsaved-changes";

import { NoFeesAccess, amountClass, tdClass, thClass } from "../../fees";
import { Payments } from "./payments";

// One student's bill for a term (E1): its fees and adjustments, the total,
// the guardians to contact about it, and (for those who manage fees) adding
// an optional item or an adjustment. Nothing on a bill is ever changed.
// E2: what has been paid and what is still owed, and the payments.
// E3: the balance from earlier terms, the amount due now, and links to the
// student's fee statement and a printable bill.

export function BillPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/fees">{(me) => <Content me={me} billId={id} />}</AppShell>;
}

function Content({ me, billId }: { me: Me; billId: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Bill" />;
  }
  return <BillView key={school.id} billId={billId} />;
}

function BillView({ billId }: { billId: string }) {
  const [bill, setBill] = useState<Bill | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Payment | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Bill>(`/school/fees/bills/${billId}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(billPath(billId));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setBill(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [billId]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Bill not found</h1>
        <p>
          This bill does not exist, or it is not in this school.{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!bill) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  const hasEarlier = bill.earlier.balance_kes !== 0 || bill.earlier.bills.length > 0;

  function changed(next: Bill, message: string, newReceipt?: Payment) {
    setBill(next);
    setNotice(message);
    setReceipt(newReceipt ?? null);
  }

  return (
    <>
      <p className="mb-2">
        <Link href={gradeFeesPath(bill.year.id, bill.term.number, bill.grade.code)} className="text-sm text-link underline underline-offset-2">
          Back to {bill.grade.name} fees
        </Link>
      </p>
      <h1 className="mb-1 text-[1.9375rem] leading-tight font-bold tracking-tight break-words">Bill for {bill.student.full_name}</h1>
      <p className="mb-2 break-words text-muted">
        Admission no. {bill.student.admission_number}, {bill.class_name}, Term {bill.term.number} of {bill.year.name}
      </p>
      <p className="mb-6 flex flex-wrap gap-x-4 gap-y-1">
        <Link href={statementPath(bill.student.id)} className="text-link underline underline-offset-2">
          Fee statement
        </Link>
        <Link href={billPrintPath(bill.id)} className="text-link underline underline-offset-2">
          Print bill
        </Link>
      </p>

      {notice && (
        <Notice>
          {notice}
          {receipt && (
            <>
              {" "}
              <Link href={receiptPath(receipt.id)} className="font-semibold text-link underline underline-offset-2">
                View receipt {formatReceiptNumber(receipt.receipt_number)}
              </Link>
            </>
          )}
        </Notice>
      )}

      <section aria-labelledby="lines-heading" className="mb-8 max-w-3xl">
        <h2 id="lines-heading" className="mb-3 text-xl font-semibold">
          What is owed
        </h2>
        <div className="overflow-x-auto">
          {/* One block per line on phones (stack-table, globals.css). */}
          <table className="stack-table w-full border-collapse text-left text-sm">
            <caption className="sr-only">Bill lines</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>
                  Item or reason
                </th>
                <th scope="col" className={`${thClass} ${amountClass}`}>
                  Amount
                </th>
                <th scope="col" className={thClass}>
                  Added
                </th>
              </tr>
            </thead>
            <tbody>
              {bill.lines.length === 0 && (
                <tr>
                  <td colSpan={3} className={tdClass}>
                    No fees on this bill.
                  </td>
                </tr>
              )}
              {bill.lines.map((line) => (
                <tr key={line.id}>
                  <th scope="row" className={`${tdClass} font-normal break-words`}>
                    {line.kind === "adjustment" ? `Adjustment: ${line.description}` : line.description}
                  </th>
                  <td data-label="Amount" className={`${tdClass} ${amountClass}`}>
                    {formatKes(line.amount_kes)}
                  </td>
                  <td data-label="Added" className={tdClass}>
                    {line.created_at && formatDayOf(line.created_at)}
                    {line.created_by && `, ${line.created_by}`}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" className="px-2 py-2 text-base font-semibold">
                  Total
                </th>
                <td className={`px-2 py-2 text-base font-semibold ${amountClass}`}>{formatKes(bill.total_kes)}</td>
                <td />
              </tr>
              <tr>
                <th scope="row" className="px-2 py-1 font-normal">
                  Paid
                </th>
                <td className={`px-2 py-1 ${amountClass}`}>{formatKes(bill.paid_kes)}</td>
                <td />
              </tr>
              <tr>
                <th scope="row" className="px-2 py-1 text-base font-semibold">
                  Balance
                </th>
                <td className={`px-2 py-1 text-base font-semibold ${amountClass}`}>{formatBalance(bill.balance_kes)}</td>
                <td />
              </tr>
              {hasEarlier && (
                <>
                  <tr>
                    <th scope="row" className="px-2 py-1 font-normal">
                      From earlier terms
                    </th>
                    <td className={`px-2 py-1 ${amountClass}`}>{formatBalance(bill.earlier.balance_kes)}</td>
                    <td />
                  </tr>
                  <tr>
                    <th scope="row" className="px-2 py-1 text-base font-semibold">
                      Amount due now
                    </th>
                    <td className={`px-2 py-1 text-base font-semibold ${amountClass}`}>
                      {formatBalance(bill.due_now_kes)}
                    </td>
                    <td />
                  </tr>
                </>
              )}
            </tfoot>
          </table>
        </div>
        {bill.earlier.bills.length > 0 && <EarlierBills bill={bill} />}
      </section>

      <Payments bill={bill} onChanged={changed} />

      {bill.can_manage && (
        <div className="mb-8 grid max-w-3xl gap-8 md:grid-cols-2">
          <AddOptionalItem bill={bill} onAdded={(next, name) => changed(next, `${name} added to the bill.`)} />
          <AddAdjustment bill={bill} onAdded={(next) => changed(next, "Adjustment saved.")} />
        </div>
      )}

      <Guardians bill={bill} />
    </>
  );
}

// The earlier bills that are not settled, so staff can open them (a payment
// is recorded against the bill the family means it for).
function EarlierBills({ bill }: { bill: Bill }) {
  return (
    <div className="mt-3 text-sm">
      <p className="text-muted">Earlier terms not settled:</p>
      <ul className="list-disc pl-5">
        {bill.earlier.bills.map((earlier) => (
          <li key={earlier.id}>
            <Link
              href={billPath(earlier.id)}
              className="text-link underline underline-offset-2"
              aria-label={`${termLabel(earlier.term, earlier.year)} bill`}
            >
              {termLabel(earlier.term, earlier.year)}
            </Link>
            : {earlier.balance_kes > 0 ? `${formatKes(earlier.balance_kes)} owed` : formatBalance(earlier.balance_kes)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AddOptionalItem({ bill, onAdded }: { bill: Bill; onAdded: (next: Bill, name: string) => void }) {
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const items = bill.optional_items;

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const item = items.find((i) => i.id === chosen);
    if (!item) {
      setError("Choose an optional item.");
      return;
    }
    setPending(true);
    const response = await api<Bill>(`/school/fees/bills/${bill.id}/items`, {
      method: "POST",
      body: { fee_item_id: item.id },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(billPath(bill.id));
    } else if (response.ok) {
      setChosen("");
      onAdded(response.data, item.name);
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <section aria-labelledby="optional-heading">
      <h2 id="optional-heading" className="mb-3 text-lg font-semibold">
        Add an optional item
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted">
          No optional items left to add for {bill.grade.name} this term.
        </p>
      ) : (
        <form onSubmit={add} noValidate>
          <ErrorMessage message={error} />
          <label htmlFor="optional-item" className={labelClass}>
            Optional item
          </label>
          <select
            id="optional-item"
            className={`${inputClass} mb-3`}
            value={chosen}
            onChange={(event) => setChosen(event.target.value)}
          >
            <option value="">Choose an item</option>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({formatKes(item.amount_kes)})
              </option>
            ))}
          </select>
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Adding..." : "Add to bill"}
          </button>
        </form>
      )}
    </section>
  );
}

function AddAdjustment({ bill, onAdded }: { bill: Bill; onAdded: (next: Bill) => void }) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  useUnsavedChanges(amount.trim() !== "" || reason.trim() !== "", () => {
    setAmount("");
    setReason("");
  });

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const value = parseAmount(amount, { allowNegative: true });
    const problems = [];
    if (typeof value === "string") {
      problems.push(value);
    } else if (bill.total_kes + value < 0) {
      problems.push(`A bill's total cannot go below 0: it can be reduced by at most ${formatKes(bill.total_kes)}.`);
    }
    if (!reason.trim()) {
      problems.push("Enter a reason.");
    }
    if (problems.length > 0) {
      setError(problems.join(" "));
      return;
    }
    setPending(true);
    const response = await api<Bill>(`/school/fees/bills/${bill.id}/adjustments`, {
      method: "POST",
      body: { amount_kes: value, reason: reason.trim() },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(billPath(bill.id));
    } else if (response.ok) {
      setAmount("");
      setReason("");
      onAdded(response.data);
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <section aria-labelledby="adjustment-heading">
      <h2 id="adjustment-heading" className="mb-3 text-lg font-semibold">
        Add an adjustment
      </h2>
      <form onSubmit={save} noValidate>
        <ErrorMessage message={error} />
        <label htmlFor="adjustment-amount" className={labelClass}>
          Amount (KES)
        </label>
        <p id="adjustment-amount-hint" className="mb-1 text-sm text-muted">
          Put a minus sign in front to reduce the bill, for example -5000 for a bursary.
        </p>
        <input
          id="adjustment-amount"
          className={`${inputClass} mb-3`}
          inputMode="text"
          aria-describedby="adjustment-amount-hint"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
        <label htmlFor="adjustment-reason" className={labelClass}>
          Reason
        </label>
        <input
          id="adjustment-reason"
          className={`${inputClass} mb-3`}
          maxLength={MAX_ADJUSTMENT_REASON}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button type="submit" className={inlineButtonClass} disabled={pending}>
          {pending ? "Saving..." : "Save adjustment"}
        </button>
      </form>
    </section>
  );
}

function Guardians({ bill }: { bill: Bill }) {
  return (
    <section aria-labelledby="guardians-heading" className="max-w-3xl">
      <h2 id="guardians-heading" className="mb-1 text-xl font-semibold">
        Guardians to contact
      </h2>
      <p className="mb-3 text-sm text-muted">For questions about this bill only.</p>
      {bill.guardians.length === 0 ? (
        <p className="text-sm">No guardians are recorded for {bill.student.full_name}.</p>
      ) : (
        <ul className="space-y-3">
          {bill.guardians.map((guardian) => (
            <li key={guardian.phone} className="rounded-lg border border-rule p-3 break-words">
              <p className="font-medium">
                {guardian.full_name}
                <span className="ml-2 text-sm font-normal text-muted">
                  {relationshipLabel(guardian.relationship as Relationship)}
                  {guardian.is_primary && ", main contact"}
                </span>
              </p>
              <p className="text-sm">
                Phone:{" "}
                <a href={`tel:${guardian.phone}`} className="text-link underline underline-offset-2">
                  {guardian.phone}
                </a>
              </p>
              {guardian.email && (
                <p className="text-sm">
                  Email:{" "}
                  <a href={`mailto:${guardian.email}`} className="text-link underline underline-offset-2">
                    {guardian.email}
                  </a>
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
