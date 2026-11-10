"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import {
  arrearsPath,
  canSeeFees,
  describeFeesError,
  formatDate,
  formatKes,
  methodLabel,
  statementPath,
  termLabel,
  type ClassRef,
  type OwingStudent,
  type StudentsOwing,
} from "@/lib/fees";
import { formatPhone, relationshipLabel, type Relationship } from "@/lib/guardians";

import { NoFeesAccess, amountClass, tdClass, thClass } from "../fees";

// Students owing fees across all terms (E4): who owes what, how much of it
// is overdue, and whom to call; filtered by class, overdue only or a
// minimum amount, and printable as a list (A4 landscape). The filters live
// in the address, so a filtered list can be bookmarked or reloaded.

type Filters = {
  grade: string;
  classId: string;
  overdue: boolean;
  min: string;
  order: "owed" | "class";
};

function filtersFrom(params: URLSearchParams): Filters {
  return {
    grade: params.get("grade") ?? "",
    classId: params.get("class") ?? "",
    overdue: params.get("overdue") === "1",
    min: /^\d+$/.test(params.get("min") ?? "") ? params.get("min")! : "",
    order: params.get("order") === "class" ? "class" : "owed",
  };
}

function addressOf(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.grade) params.set("grade", filters.grade);
  if (filters.classId) params.set("class", filters.classId);
  if (filters.overdue) params.set("overdue", "1");
  if (filters.min) params.set("min", filters.min);
  if (filters.order === "class") params.set("order", "class");
  const query = params.toString();
  return query ? `${arrearsPath()}?${query}` : arrearsPath();
}

function apiQuery(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.grade) params.set("grade", filters.grade);
  if (filters.classId) params.set("class_id", filters.classId);
  if (filters.overdue) params.set("overdue", "true");
  if (filters.min) params.set("min_kes", filters.min);
  const query = params.toString();
  return `/school/fees/arrears${query ? `?${query}` : ""}`;
}

export function StudentsOwingPage() {
  const params = useSearchParams();
  const filters = filtersFrom(params);
  return <AppShell path="/fees">{(me) => <Content me={me} filters={filters} />}</AppShell>;
}

function Content({ me, filters }: { me: Me; filters: Filters }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Students owing" />;
  }
  // A new list for each school and each set of filters (the order is only
  // a different arrangement of the same list).
  const { order, ...asked } = filters;
  return <OwingView key={`${school.id}/${JSON.stringify(asked)}`} filters={filters} order={order} />;
}

function OwingView({ filters, order }: { filters: Filters; order: Filters["order"] }) {
  const [data, setData] = useState<StudentsOwing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = apiQuery(filters);
  const address = addressOf(filters);

  useEffect(() => {
    let cancelled = false;
    api<StudentsOwing>(query).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(address);
      } else if (response.ok) {
        setData(response.data);
      } else if (response.status === 422) {
        setError(`${describeFeesError(response.status, response.error)} Clear the filters to see everyone owing.`);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [query, address]);

  return (
    <div className="arrears-list">
      <div className="print:hidden">
        <p className="mb-2">
          <Link href="/fees" className="text-sm text-link underline underline-offset-2">
            Back to fees
          </Link>
        </p>
        <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight">Students owing</h1>
          {data && data.students.length > 0 && (
            <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
              Print list
            </button>
          )}
        </div>
        <p className="mb-6 max-w-2xl text-sm text-muted">
          Everyone whose bills, all terms added together, still have something to pay, largest amount first. Overdue is
          the part owed on bills whose pay-by date has passed. Guardian contacts are for fee follow-up only.
        </p>
      </div>
      {data ? (
        <>
          <FilterForm data={data} filters={filters} />
          <PrintHeading data={data} filters={filters} />
          <OwingTable
            data={data}
            filters={filters}
            order={order}
            filtered={!!(filters.grade || filters.classId || filters.overdue || filters.min)}
          />
        </>
      ) : error ? (
        <>
          <ErrorMessage message={error} />
          <Link href={arrearsPath()} className="text-link underline underline-offset-2">
            Clear filters
          </Link>
        </>
      ) : (
        <p className="text-muted">Loading...</p>
      )}
    </div>
  );
}

function describeFilters(data: StudentsOwing, filters: Filters): string {
  const parts: string[] = [];
  const chosenClass = data.filters.classes.find((c) => c.id === filters.classId);
  if (chosenClass) {
    parts.push(chosenClass.name);
  } else if (filters.grade) {
    parts.push(data.filters.grades.find((g) => g.code === filters.grade)?.name ?? filters.grade);
  }
  if (filters.overdue) parts.push("overdue only");
  if (filters.min) parts.push(`owing at least ${formatKes(Number(filters.min))}`);
  return parts.length > 0 ? parts.join(", ") : "all students owing";
}

function FilterForm({ data, filters }: { data: StudentsOwing; filters: Filters }) {
  const router = useRouter();
  const [grade, setGrade] = useState(filters.grade);
  const [classId, setClassId] = useState(filters.classId);
  const [overdue, setOverdue] = useState(filters.overdue);
  const [min, setMin] = useState(filters.min);
  const [problem, setProblem] = useState<string | null>(null);
  const classes = data.filters.classes.filter((c) => !grade || c.grade === grade);
  // Classes of the same name in different years (a student who left in an
  // earlier year) are told apart by the year.
  const label = (c: ClassRef) =>
    data.filters.classes.filter((other) => other.name === c.name).length > 1 ? `${c.name}, ${c.year.name}` : c.name;

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleaned = min.replace(/[\s,]/g, "");
    if (cleaned && (!/^\d+$/.test(cleaned) || Number(cleaned) < 1)) {
      setProblem("Enter the amount as a whole number of shillings, such as 5000.");
      return;
    }
    setProblem(null);
    router.replace(
      addressOf({
        grade,
        classId,
        overdue,
        min: cleaned,
        order: filters.order,
      }),
    );
  }

  return (
    <form onSubmit={apply} noValidate aria-label="Filter the list" className="mb-6 print:hidden">
      <ErrorMessage message={problem} />
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 basis-40">
          <label htmlFor="grade" className={labelClass}>
            Grade
          </label>
          <select
            id="grade"
            className={inputClass}
            value={grade}
            onChange={(event) => {
              setGrade(event.target.value);
              setClassId("");
            }}
          >
            <option value="">All grades</option>
            {data.filters.grades.map((g) => (
              <option key={g.code} value={g.code}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-0 basis-48">
          <label htmlFor="class" className={labelClass}>
            Class
          </label>
          <select
            id="class"
            className={inputClass}
            value={classId}
            onChange={(event) => setClassId(event.target.value)}
          >
            <option value="">All classes</option>
            {classes.map((c) => (
              <option key={c.id} value={c.id}>
                {label(c)}
              </option>
            ))}
          </select>
        </div>
        <div className="w-44">
          <label htmlFor="min" className={labelClass}>
            Owing at least (KES)
          </label>
          <input
            id="min"
            className={inputClass}
            inputMode="numeric"
            value={min}
            onChange={(event) => setMin(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-2 py-2">
          <input
            id="overdue"
            type="checkbox"
            className="h-4 w-4"
            checked={overdue}
            onChange={(event) => setOverdue(event.target.checked)}
          />
          <label htmlFor="overdue" className="text-sm">
            Overdue only
          </label>
        </div>
        <div className="flex gap-3">
          <button type="submit" className={inlineButtonClass}>
            Show
          </button>
          <Link href={arrearsPath()} className={secondaryButtonClass}>
            Clear filters
          </Link>
        </div>
      </div>
    </form>
  );
}

// A different arrangement of the same list: no new request.
function OrderPicker({ filters, order }: { filters: Filters; order: Filters["order"] }) {
  const router = useRouter();
  return (
    <div className="flex items-center gap-2 print:hidden">
      <label htmlFor="order" className="text-sm font-medium">
        Order
      </label>
      <select
        id="order"
        className={`${inputClass} w-auto py-1`}
        value={order}
        onChange={(event) =>
          router.replace(
            addressOf({
              ...filters,
              order: event.target.value === "class" ? "class" : "owed",
            }),
          )
        }
      >
        <option value="owed">Largest amount first</option>
        <option value="class">By class</option>
      </select>
    </div>
  );
}

// Only on paper: what the list is, when it was printed and that it is
// confidential (the screen shows the page heading and filters instead).
function PrintHeading({ data, filters }: { data: StudentsOwing; filters: Filters }) {
  return (
    <header className="mb-3 hidden border-b border-rule-strong pb-2 print:block">
      <p className="text-xl font-bold">{data.school.name}</p>
      <p className="font-semibold">Students owing fees, {formatDate(data.today)}</p>
      <p className="text-sm">Showing {describeFilters(data, filters)}.</p>
      <p className="text-sm font-semibold">Confidential: guardian contacts for fee follow-up only.</p>
    </header>
  );
}

function byClass(a: OwingStudent, b: OwingStudent, classOrder: string[]): number {
  const rank = (row: OwingStudent) => (row.class ? classOrder.indexOf(row.class.id) : classOrder.length);
  return rank(a) - rank(b) || a.student.full_name.localeCompare(b.student.full_name);
}

function OwingTable({
  data,
  filters,
  order,
  filtered,
}: {
  data: StudentsOwing;
  filters: Filters;
  order: Filters["order"];
  filtered: boolean;
}) {
  if (data.students.length === 0) {
    return (
      <p role="status">
        {filtered ? "No student owing matches these filters." : `No student owes fees on ${formatDate(data.today)}.`}
      </p>
    );
  }
  const classOrder = data.filters.classes.map((c) => c.id);
  const rows = order === "class" ? [...data.students].sort((a, b) => byClass(a, b, classOrder)) : data.students;
  const { totals } = data;
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 print:hidden">
        <p role="status">
          {totals.students} student{totals.students === 1 ? "" : "s"} owe
          {totals.students === 1 ? "s" : ""} <span className="font-semibold">{formatKes(totals.owed_kes)}</span>
          {totals.overdue_kes > 0 ? (
            <>
              , of which <span className="font-semibold">{formatKes(totals.overdue_kes)}</span> is overdue
            </>
          ) : null}
          .
        </p>
        <OrderPicker filters={filters} order={order} />
      </div>
      <div>
        <table className="stack-table w-full border-collapse text-left text-sm">
          <caption className="sr-only">Students owing fees</caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>
                Student
              </th>
              <th scope="col" className={thClass}>
                Class
              </th>
              <th scope="col" className={`${thClass} ${amountClass}`}>
                Owed now
              </th>
              <th scope="col" className={`${thClass} ${amountClass}`}>
                Overdue
              </th>
              <th scope="col" className={thClass}>
                Oldest unpaid
              </th>
              <th scope="col" className={thClass}>
                Last payment
              </th>
              <th scope="col" className={thClass}>
                Contact
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.student.id} className="break-inside-avoid">
                <th scope="row" className={`${tdClass} font-normal break-words`}>
                  <Link
                    href={statementPath(row.student.id)}
                    className="font-medium text-link underline underline-offset-2 print:text-ink print:no-underline"
                    aria-label={`${row.student.full_name}'s fee statement`}
                  >
                    {row.student.full_name}
                  </Link>
                  <span className="block text-muted">Adm. {row.student.admission_number}</span>
                  {row.left_school && (
                    <span className="mt-0.5 inline-block rounded-sm border border-rule-strong px-1.5 text-xs font-semibold">
                      Left school
                    </span>
                  )}
                </th>
                <td data-label="Class" className={`${tdClass} break-words`}>
                  {row.class?.name ?? "No class"}
                </td>
                <td data-label="Owed now" className={`${tdClass} ${amountClass} font-semibold`}>
                  {formatKes(row.owed_kes)}
                </td>
                <td data-label="Overdue" className={`${tdClass} ${amountClass}`}>
                  {row.overdue_kes > 0 ? formatKes(row.overdue_kes) : "None"}
                </td>
                <td data-label="Oldest unpaid" className={tdClass}>
                  {row.oldest_unpaid ? termLabel(row.oldest_unpaid.term, row.oldest_unpaid.year) : "—"}
                </td>
                <td data-label="Last payment" className={tdClass}>
                  {row.last_payment ? (
                    <>
                      {formatDate(row.last_payment.paid_on)}:{" "}
                      <span className="whitespace-nowrap">{formatKes(row.last_payment.amount_kes)}</span> (
                      {methodLabel(row.last_payment.method)})
                    </>
                  ) : (
                    "None"
                  )}
                </td>
                <td data-label="Contact" className={`${tdClass} break-words`}>
                  {row.contact ? (
                    <>
                      {row.contact.full_name} (
                      {relationshipLabel(row.contact.relationship as Relationship).toLowerCase()})
                      <a
                        href={`tel:${row.contact.phone}`}
                        className="block whitespace-nowrap text-link underline underline-offset-2 print:text-ink print:no-underline"
                        aria-label={`Call ${row.contact.full_name} on ${formatPhone(row.contact.phone)}`}
                      >
                        {formatPhone(row.contact.phone)}
                      </a>
                    </>
                  ) : (
                    "No guardian recorded"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={2} className="px-2 py-2 font-medium">
                All {totals.students} student{totals.students === 1 ? "" : "s"}
              </th>
              <td className={`px-2 py-2 font-medium ${amountClass}`}>
                <span className="sr-only">Owed now: </span>
                {formatKes(totals.owed_kes)}
              </td>
              {/* On a phone the line above the list gives the overdue total. */}
              <td className={`px-2 py-2 font-medium ${amountClass} max-sm:hidden`}>
                <span className="sr-only">Overdue: </span>
                {formatKes(totals.overdue_kes)}
              </td>
              <td colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mt-3 hidden text-sm font-semibold print:block">
        Confidential: guardian contacts for fee follow-up only.
      </p>
    </>
  );
}
