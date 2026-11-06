"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import {
  MAX_FEE_ITEMS,
  MAX_FEE_ITEM_NAME,
  billPath,
  canSeeFees,
  describeFeesError,
  feesPath,
  formatDayOf,
  formatKes,
  parseAmount,
  type GradeFees,
  type IssueResult,
  type Structure,
} from "@/lib/fees";
import { useUnsavedChanges } from "@/lib/unsaved-changes";

import { NoFeesAccess, amountClass, tdClass, thClass } from "../../../fees";

// One grade's fees for a term (E1): its fee structure (edited until bills
// are issued), issuing bills, and the students' bills.

export function GradeFeesPage() {
  const params = useParams<{ yearId: string; term: string; grade: string }>();
  return (
    <AppShell path="/fees">
      {(me) => <Content me={me} yearId={params.yearId} term={Number(params.term)} grade={params.grade} />}
    </AppShell>
  );
}

function Content({ me, yearId, term, grade }: { me: Me; yearId: string; term: number; grade: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Grade fees" />;
  }
  return <Grade key={school.id} yearId={yearId} term={term} grade={grade} />;
}

function Grade({ yearId, term, grade }: { yearId: string; term: number; grade: string }) {
  const path = `/school/fees/years/${yearId}/terms/${term}/grades/${grade}`;
  const here = `/fees/${yearId}/${term}/${grade}`;
  const [data, setData] = useState<GradeFees | null>(null);
  const [notFound, setNotFound] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Unsaved changes to the structure: bills are issued from the saved one.
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<GradeFees>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(here);
      } else if (!response.ok && response.status === 404) {
        setNotFound(response.error.message);
      } else if (response.ok) {
        setData(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, here]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Fees not found</h1>
        <p>
          {notFound}{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!data) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  const structure = data.structure;
  const issued = structure?.issued_at != null;
  const editable = data.can_manage && !issued;

  function updated(next: GradeFees, message: string) {
    setData(next);
    setNotice(message);
  }

  return (
    <>
      <p className="mb-2">
        <Link href={feesPath(yearId, term)} className="text-sm text-link underline underline-offset-2">
          Back to fees
        </Link>
      </p>
      <h1 className="mb-1 text-[1.9375rem] leading-tight font-bold tracking-tight">{data.grade.name} fees</h1>
      <p className="mb-6 text-muted">
        Term {data.term.number}, {data.year.name}
      </p>

      {notice && <Notice>{notice}</Notice>}

      <section aria-labelledby="structure-heading" className="mb-8">
        <h2 id="structure-heading" className="mb-3 text-xl font-semibold">
          Fee structure
        </h2>
        {editable ? (
          <StructureEditor
            path={path}
            here={here}
            structure={structure}
            onDirty={setEditing}
            onSaved={(next) => updated(next, "Fee structure saved.")}
          />
        ) : structure && structure.items.length > 0 ? (
          <StructureView structure={structure} />
        ) : (
          <p>No fee structure yet for this term.</p>
        )}
        {issued && structure && (
          <p className="mt-3 max-w-2xl text-sm text-muted">
            Bills were first issued on {formatDayOf(structure.issued_at!)}
            {structure.issued_by && ` by ${structure.issued_by}`}. The fee structure can no longer be changed:
            correct single bills with adjustments.
          </p>
        )}
      </section>

      {data.can_manage && structure && structure.items.length > 0 && data.not_billed.length > 0 && (
        <IssueBills
          path={path}
          here={here}
          data={data}
          editing={editing}
          onIssued={(next) =>
            updated(next, `${next.billed} bill${next.billed === 1 ? "" : "s"} issued for Term ${next.term.number}.`)
          }
        />
      )}

      <Bills data={data} />
    </>
  );
}

function StructureView({ structure }: { structure: Structure }) {
  return (
    <div className="max-w-2xl overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Fee items</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>
              Item
            </th>
            <th scope="col" className={`${thClass} ${amountClass}`}>
              Amount
            </th>
            <th scope="col" className={thClass}>
              Who pays
            </th>
          </tr>
        </thead>
        <tbody>
          {structure.items.map((item) => (
            <tr key={item.id}>
              <th scope="row" className={`${tdClass} font-normal`}>
                {item.name}
              </th>
              <td className={`${tdClass} ${amountClass}`}>{formatKes(item.amount_kes)}</td>
              <td className={tdClass}>{item.is_optional ? "Optional, added per student" : "Every student"}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" className="px-2 py-2 font-medium">
              Compulsory fees
            </th>
            <td className={`px-2 py-2 font-medium ${amountClass}`}>{formatKes(structure.compulsory_total_kes)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

type Row = { key: number; name: string; amount: string; optional: boolean };

let nextKey = 1;

function rowsFrom(structure: Structure | null): Row[] {
  if (!structure || structure.items.length === 0) {
    return [{ key: nextKey++, name: "", amount: "", optional: false }];
  }
  return structure.items.map((item) => ({
    key: nextKey++,
    name: item.name,
    amount: String(item.amount_kes),
    optional: item.is_optional,
  }));
}

function sameRows(a: Row[], b: Row[]): boolean {
  const clean = (rows: Row[]) =>
    rows
      .filter((r) => r.name.trim() || r.amount.trim())
      .map((r) => `${r.name.trim()}|${r.amount.replace(/[\s,]/g, "")}|${r.optional}`)
      .join("\n");
  return clean(a) === clean(b);
}

function StructureEditor({
  path,
  here,
  structure,
  onDirty,
  onSaved,
}: {
  path: string;
  here: string;
  structure: Structure | null;
  onDirty: (dirty: boolean) => void;
  onSaved: (next: GradeFees) => void;
}) {
  const [saved, setSaved] = useState<Row[]>(() => rowsFrom(structure));
  const [rows, setRows] = useState<Row[]>(saved);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const dirty = !sameRows(rows, saved);
  useUnsavedChanges(dirty, () => setRows(saved));
  useEffect(() => onDirty(dirty), [dirty, onDirty]);

  const total = rows.reduce((sum, row) => {
    const value = parseAmount(row.amount);
    return !row.optional && typeof value === "number" ? sum + value : sum;
  }, 0);

  function change(key: number, update: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...update } : row)));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const used = rows.filter((r) => r.name.trim() || r.amount.trim());
    const problems: string[] = [];
    const seen = new Set<string>();
    const items = used.map((row, index) => {
      const label = row.name.trim() || `Item ${index + 1}`;
      const amount = parseAmount(row.amount);
      if (!row.name.trim()) {
        problems.push(`Item ${index + 1}: enter a name.`);
      } else if (seen.has(row.name.trim().toLowerCase())) {
        problems.push(`${label}: another item has the same name.`);
      }
      seen.add(row.name.trim().toLowerCase());
      if (typeof amount === "string") {
        problems.push(`${label}: ${amount}`);
      }
      return { name: row.name.trim(), amount_kes: amount, is_optional: row.optional };
    });
    if (problems.length > 0) {
      setError(problems.join(" "));
      return;
    }
    setPending(true);
    const response = await api<GradeFees>(path, { method: "PUT", body: { items } });
    setPending(false);
    if (response.status === 401) {
      goToLogin(here);
    } else if (response.ok) {
      const next = rowsFrom(response.data.structure);
      setSaved(next);
      setRows(next);
      onSaved(response.data);
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={save} noValidate className="max-w-2xl">
      <p className="mb-4 text-sm text-muted">
        List this term&apos;s fees in whole shillings. Every student is billed the compulsory items; optional items
        (such as boarding or transport) are added to single students&apos; bills. Up to {MAX_FEE_ITEMS} items.
      </p>
      <ErrorMessage message={error} />
      <ol className="mb-4 space-y-3">
        {rows.map((row, index) => (
          <li key={row.key}>
            <fieldset className="flex flex-wrap items-end gap-3 rounded-lg border border-rule p-3">
              <legend className="sr-only">Item {index + 1}</legend>
              <div className="min-w-0 flex-1 basis-40">
                <label htmlFor={`name-${row.key}`} className={labelClass}>
                  Name
                </label>
                <input
                  id={`name-${row.key}`}
                  className={inputClass}
                  value={row.name}
                  maxLength={MAX_FEE_ITEM_NAME}
                  onChange={(event) => change(row.key, { name: event.target.value })}
                />
              </div>
              <div className="w-36">
                <label htmlFor={`amount-${row.key}`} className={labelClass}>
                  Amount (KES)
                </label>
                <input
                  id={`amount-${row.key}`}
                  className={inputClass}
                  inputMode="numeric"
                  value={row.amount}
                  onChange={(event) => change(row.key, { amount: event.target.value })}
                />
              </div>
              <div className="flex items-center gap-2 py-2">
                <input
                  id={`optional-${row.key}`}
                  type="checkbox"
                  className="h-4 w-4"
                  checked={row.optional}
                  onChange={(event) => change(row.key, { optional: event.target.checked })}
                />
                <label htmlFor={`optional-${row.key}`} className="text-sm">
                  Optional
                </label>
              </div>
              <button
                type="button"
                className={secondaryButtonClass}
                onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
              >
                Remove<span className="sr-only"> item {index + 1}</span>
              </button>
            </fieldset>
          </li>
        ))}
      </ol>
      <p className="mb-4 text-sm" aria-live="polite">
        Compulsory fees per student: <span className="font-medium">{formatKes(total)}</span>
      </p>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          className={secondaryButtonClass}
          disabled={rows.length >= MAX_FEE_ITEMS}
          onClick={() =>
            setRows((current) => [...current, { key: nextKey++, name: "", amount: "", optional: false }])
          }
        >
          Add item
        </button>
        <button type="submit" className={inlineButtonClass} disabled={pending || !dirty}>
          {pending ? "Saving..." : "Save fee structure"}
        </button>
      </div>
    </form>
  );
}

function IssueBills({
  path,
  here,
  data,
  editing,
  onIssued,
}: {
  path: string;
  here: string;
  data: GradeFees;
  editing: boolean;
  onIssued: (next: IssueResult) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const count = data.not_billed.length;
  const students = `${count} student${count === 1 ? "" : "s"}`;
  const first = data.bills.length === 0;

  async function issue() {
    setError(null);
    setPending(true);
    const response = await api<IssueResult>(`${path}/issue`, { method: "POST" });
    setPending(false);
    setConfirming(false);
    if (response.status === 401) {
      goToLogin(here);
    } else if (response.ok) {
      onIssued(response.data);
    } else {
      setError(describeFeesError(response.status, response.error));
    }
  }

  return (
    <section aria-labelledby="issue-heading" className="mb-8 max-w-2xl">
      <h2 id="issue-heading" className="mb-3 text-xl font-semibold">
        {first ? "Issue bills" : `${students} not billed yet`}
      </h2>
      <ErrorMessage message={error} />
      {first ? (
        <p className="mb-3 text-sm">
          Each active student of {data.grade.name} gets a bill for Term {data.term.number} with the compulsory items
          ({formatKes(data.structure!.compulsory_total_kes)}). After that, the fee structure can no longer be changed.
        </p>
      ) : (
        <ul className="mb-3 list-disc pl-6 text-sm break-words">
          {data.not_billed.map((row) => (
            <li key={row.student.id}>
              {row.student.full_name} ({row.student.admission_number}), {row.class_name}
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <p className="text-sm font-medium">Save the fee structure before issuing bills.</p>
      ) : !confirming ? (
        <button type="button" className={inlineButtonClass} onClick={() => setConfirming(true)}>
          {first ? `Issue bills to ${students}` : `Bill ${students} not billed yet`}
        </button>
      ) : (
        <div className="rounded-md border-l-4 border-warn-border bg-warn-soft p-4">
          <p className="mb-3 text-sm font-medium" id="issue-confirm">
            Issue {count} bill{count === 1 ? "" : "s"} for Term {data.term.number}? Bills cannot be deleted; mistakes
            are corrected with adjustments.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              className={inlineButtonClass}
              aria-describedby="issue-confirm"
              disabled={pending}
              onClick={issue}
            >
              {pending ? "Issuing..." : `Yes, issue ${count} bill${count === 1 ? "" : "s"}`}
            </button>
            <button type="button" className={secondaryButtonClass} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Bills({ data }: { data: GradeFees }) {
  if (data.bills.length === 0) {
    return null;
  }
  const total = data.bills.reduce((sum, bill) => sum + bill.total_kes, 0);
  return (
    <section aria-labelledby="bills-heading">
      <h2 id="bills-heading" className="mb-3 text-xl font-semibold">
        Bills ({data.bills.length})
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            {data.grade.name} bills for Term {data.term.number}
          </caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>
                Student
              </th>
              <th scope="col" className={thClass}>
                Admission no.
              </th>
              <th scope="col" className={thClass}>
                Class
              </th>
              <th scope="col" className={`${thClass} ${amountClass}`}>
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {data.bills.map((bill) => (
              <tr key={bill.id}>
                <th scope="row" className={`${tdClass} font-normal`}>
                  <Link
                    href={billPath(bill.id)}
                    className="text-link underline underline-offset-2"
                    aria-label={`${bill.student.full_name}'s bill`}
                  >
                    {bill.student.full_name}
                  </Link>
                </th>
                <td className={tdClass}>{bill.student.admission_number}</td>
                <td className={tdClass}>{bill.class_name}</td>
                <td className={`${tdClass} ${amountClass}`}>{formatKes(bill.total_kes)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3} className="px-2 py-2 font-medium">
                All bills
              </th>
              <td className={`px-2 py-2 font-medium ${amountClass}`}>{formatKes(total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}
