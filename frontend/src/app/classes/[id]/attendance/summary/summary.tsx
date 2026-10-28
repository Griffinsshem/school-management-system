"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { formatCalendarDate, type AcademicYear, type AcademicYearList } from "@/lib/academic-years";
import {
  canSeeAttendance,
  kenyaToday,
  registerPath,
  type Counts,
  type TermSummary,
} from "@/lib/attendance";
import type { ClassList } from "@/lib/enrolments";

const MENU_PATH = "/attendance";

export function Summary() {
  const { id } = useParams<{ id: string }>();
  const asked = Number(useSearchParams().get("term"));
  const term = [1, 2, 3].includes(asked) ? asked : null;
  return <AppShell path={MENU_PATH}>{(me) => <Content me={me} classId={id} term={term} />}</AppShell>;
}

function Content({ me, classId, term }: { me: Me; classId: string; term: number | null }) {
  const school = me.active_school;
  if (!school || !canSeeAttendance(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Attendance summary</h1>
        <p>
          {school ? `You do not have access to this page in ${school.name}.` : "Choose a school first."}{" "}
          <Link href="/" className="underline">
            Go to the home page
          </Link>
          .
        </p>
      </section>
    );
  }
  return <ClassSummary key={`${school.id}/${classId}`} classId={classId} askedTerm={term} />;
}

// The term to show first: the one asked for, else today's term of the
// class's year, else the latest that has started, else the first.
function chooseTerm(year: AcademicYear, asked: number | null): number | null {
  const numbers = year.terms.map((t) => t.number);
  if (asked && numbers.includes(asked)) {
    return asked;
  }
  const today = kenyaToday();
  const started = year.terms.filter((t) => t.starts_on <= today);
  return started.at(-1)?.number ?? numbers[0] ?? null;
}

// Present or late counts as attending; none marked shows a dash.
function rate(counts: Counts): string {
  const marked = counts.present + counts.late + counts.absent;
  return marked === 0 ? "-" : `${Math.round(((counts.present + counts.late) / marked) * 100)}%`;
}

function absences(counts: Counts): string {
  const { sick, permission, unknown } = counts.absent_by_reason;
  const parts = [
    sick ? `${sick} sick` : "",
    permission ? `${permission} with permission` : "",
    unknown ? `${unknown} unknown` : "",
  ].filter(Boolean);
  return parts.length ? `${counts.absent} (${parts.join(", ")})` : String(counts.absent);
}

function ClassSummary({ classId, askedTerm }: { classId: string; askedTerm: number | null }) {
  const router = useRouter();
  const [year, setYear] = useState<AcademicYear | null>(null);
  const [className, setClassName] = useState<string | null>(null);
  const [term, setTerm] = useState<number | null>(null);
  const [summary, setSummary] = useState<TermSummary | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const here = `/classes/${classId}/attendance/summary`;

  // The class's school year, for its terms.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<ClassList>(`/school/classes/${classId}/students`),
      api<AcademicYearList>("/school/academic-years"),
    ]).then(([list, years]) => {
      if (cancelled) {
        return;
      }
      if (list.status === 401 || years.status === 401) {
        goToLogin(here);
      } else if (list.status === 404) {
        setNotFound(true);
      } else if (!list.ok) {
        setError(withReference(list.error));
      } else if (!years.ok) {
        setError(withReference(years.error));
      } else {
        const found = years.data.academic_years.find((y) => y.id === list.data.class.academic_year_id) ?? null;
        setClassName(list.data.class.name);
        setYear(found);
        setTerm(found ? chooseTerm(found, askedTerm) : null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [classId, askedTerm, here]);

  useEffect(() => {
    if (term === null) {
      return;
    }
    let cancelled = false;
    api<TermSummary>(`/school/classes/${classId}/attendance?${new URLSearchParams({ term: String(term) })}`).then(
      (response) => {
        if (cancelled) {
          return;
        }
        if (response.status === 401) {
          goToLogin(here);
        } else if (response.status === 404) {
          setNotFound(true);
        } else if (response.ok) {
          setSummary(response.data);
        } else {
          setError(withReference(response.error));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [classId, term, here]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Class not found</h1>
        <p>
          This class does not exist, or it is not one of yours.{" "}
          <Link href="/attendance" className="underline">
            Back to attendance
          </Link>
          .
        </p>
      </section>
    );
  }

  return (
    <>
      <p className="mb-2">
        <Link href={registerPath(classId, kenyaToday())} className="text-sm underline">
          Back to the register
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">
            {className ? `${className} attendance` : "Attendance summary"}
          </h1>
          {year && <p className="text-zinc-600 dark:text-zinc-400">School year {year.name}</p>}
        </div>
        {year && term !== null && (
          <div>
            <label htmlFor="term" className={labelClass}>
              Term
            </label>
            <select
              id="term"
              className={inputClass}
              value={term}
              onChange={(event) => {
                const next = Number(event.target.value);
                setSummary(null);
                setTerm(next);
                router.replace(`${here}?${new URLSearchParams({ term: String(next) })}`);
              }}
            >
              {year.terms.map((t) => (
                <option key={t.number} value={t.number}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <ErrorMessage message={error} />

      {className && !year ? (
        <p>This class&apos;s school year could not be found.</p>
      ) : year && term === null ? (
        <p>The school year {year.name} has no terms yet.</p>
      ) : !summary ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : (
        <SummaryTables summary={summary} />
      )}
    </>
  );
}

function SummaryTables({ summary }: { summary: TermSummary }) {
  const days = summary.registers.length;
  return (
    <>
      <p className="mb-4">
        Term {summary.term.number}: {formatCalendarDate(summary.term.starts_on)} to{" "}
        {formatCalendarDate(summary.term.ends_on)}. Registers taken on {days} day{days === 1 ? "" : "s"}.
      </p>

      <h2 className="mb-2 text-xl font-semibold">Students</h2>
      {summary.students.length === 0 ? (
        <p className="mb-8">No students in this class.</p>
      ) : (
        <div className="relative mb-8 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Attendance of each student in Term {summary.term.number}</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Student</th>
                <th scope="col" className={thClass}>Present / late</th>
                <th scope="col" className={thClass}>Absent</th>
                <th scope="col" className={thClass}>Attended</th>
              </tr>
            </thead>
            <tbody>
              {summary.students.map((row) => (
                <tr key={row.student.id}>
                  <th scope="row" className={`${tdClass} font-normal`}>
                    {row.student.full_name}{" "}
                    <span className="text-zinc-600 dark:text-zinc-400">({row.student.admission_number})</span>
                    {!row.in_class && (
                      <span className="block text-zinc-600 dark:text-zinc-400">No longer in this class</span>
                    )}
                  </th>
                  <td className={tdClass}>
                    {row.present} / {row.late}
                  </td>
                  <td className={tdClass}>{absences(row)}</td>
                  <td className={tdClass}>{rate(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mb-2 text-xl font-semibold">Days</h2>
      {days === 0 ? (
        <p>No registers taken in this term yet.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Each register taken in Term {summary.term.number}</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Day</th>
                <th scope="col" className={thClass}>Present / late</th>
                <th scope="col" className={thClass}>Absent</th>
              </tr>
            </thead>
            <tbody>
              {summary.registers.map((day) => (
                <tr key={day.date}>
                  <th scope="row" className={`${tdClass} font-normal`}>
                    <Link href={registerPath(summary.class.id, day.date)} className="underline">
                      {formatCalendarDate(day.date)}
                    </Link>
                  </th>
                  <td className={tdClass}>
                    {day.present} / {day.late}
                  </td>
                  <td className={tdClass}>{absences(day)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// Narrower padding on phones, so four columns fit.
const thClass = "border-b border-zinc-300 px-2 py-2 font-medium sm:px-3 dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-2 py-2 align-top sm:px-3 dark:border-zinc-800";
