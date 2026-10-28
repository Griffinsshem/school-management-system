"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import type { AcademicYearList } from "@/lib/academic-years";
import {
  canSeeAttendance,
  formatDay,
  isDate,
  kenyaToday,
  registerPath,
  type Overview,
  type Register,
} from "@/lib/attendance";
import type { ClassList } from "@/lib/classes";

const PATH = "/attendance";

export function Attendance() {
  const asked = useSearchParams().get("date");
  const date = isDate(asked) ? asked : kenyaToday();
  return <AppShell path={PATH}>{(me) => <Content me={me} date={date} />}</AppShell>;
}

function Content({ me, date }: { me: Me; date: string }) {
  const school = me.active_school;
  if (!school || !canSeeAttendance(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Attendance</h1>
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
  // Readers see every class; a teacher sees the classes they teach.
  const everyClass = me.permissions.includes("attendance.read");
  return (
    <DayPage key={`${school.id}/${date}`} schoolName={school.name} date={date} everyClass={everyClass} />
  );
}

type Row = {
  id: string;
  name: string;
  taken: boolean;
  present: number;
  absent: number;
  late: number;
};

type Day = { rows: Row[]; note: string | null };

const FUTURE: Day = { rows: [], note: "Attendance cannot be taken for a day that has not happened yet." };

// Every class of the school, from the overview (administrators, principals).
async function schoolDay(date: string): Promise<Day | { status: number; message: string }> {
  if (date > kenyaToday()) {
    return FUTURE;
  }
  const response = await api<Overview>(`/school/attendance?${new URLSearchParams({ date })}`);
  if (!response.ok) {
    return { status: response.status, message: withReference(response.error) };
  }
  const overview = response.data;
  if (!overview.academic_year_id) {
    return { rows: [], note: `No school year covers ${formatDay(date)}.` };
  }
  return {
    rows: overview.classes.map((c) => ({
      id: c.class.id,
      name: c.class.name,
      taken: c.taken,
      present: c.present,
      absent: c.absent,
      late: c.late,
    })),
    note: overview.term_number ? null : `${formatDay(date)} is not inside a term, so there are no registers.`,
  };
}

// A teacher's own classes, each with that day's register.
async function teacherDay(date: string): Promise<Day | { status: number; message: string }> {
  if (date > kenyaToday()) {
    return FUTURE;
  }
  const years = await api<AcademicYearList>("/school/academic-years");
  if (!years.ok) {
    return { status: years.status, message: withReference(years.error) };
  }
  const year = years.data.academic_years.find((y) => y.starts_on <= date && date <= y.ends_on);
  if (!year) {
    return { rows: [], note: `No school year covers ${formatDay(date)}.` };
  }
  const inTerm = year.terms.some((t) => t.starts_on <= date && date <= t.ends_on);
  const classes = await api<ClassList>(`/school/classes?${new URLSearchParams({ academic_year_id: year.id })}`);
  if (!classes.ok) {
    return { status: classes.status, message: withReference(classes.error) };
  }
  // Only class teachers take registers: a subject teacher's other classes
  // are not listed here.
  const own = classes.data.classes.filter((c) => c.is_class_teacher);
  const rows = await Promise.all(
    own.map(async (c): Promise<Row> => {
      const row = { id: c.id, name: c.name, taken: false, present: 0, absent: 0, late: 0 };
      if (!inTerm) {
        return row;
      }
      const register = await api<Register>(`/school/classes/${c.id}/attendance/${date}`);
      if (register.ok && register.data.taken) {
        row.taken = true;
        for (const mark of register.data.marks) {
          row[mark.status] += 1;
        }
      }
      return row;
    }),
  );
  return {
    rows,
    note: inTerm ? null : `${formatDay(date)} is not inside a term, so there are no registers.`,
  };
}

function DayPage({ schoolName, date, everyClass }: { schoolName: string; date: string; everyClass: boolean }) {
  const router = useRouter();
  const today = kenyaToday();
  const [day, setDay] = useState<Day | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dayText, setDayText] = useState(date);

  useEffect(() => {
    let cancelled = false;
    (everyClass ? schoolDay(date) : teacherDay(date)).then((result) => {
      if (cancelled) {
        return;
      }
      if ("rows" in result) {
        setDay(result);
      } else if (result.status === 401) {
        goToLogin(date === today ? PATH : `${PATH}?${new URLSearchParams({ date })}`);
      } else {
        setError(result.message);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [date, everyClass, today]);

  function showDay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isDate(dayText)) {
      router.push(`${PATH}?${new URLSearchParams({ date: dayText })}`);
    }
  }

  const taken = day?.rows.filter((row) => row.taken).length ?? 0;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">Attendance</h1>
          <p className="text-zinc-600 dark:text-zinc-400">
            {schoolName}: {formatDay(date)}
          </p>
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
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : day.note && day.rows.length === 0 ? (
        <p>{day.note}</p>
      ) : day.rows.length === 0 ? (
        <p>{everyClass ? "No classes in this school year yet." : "You are not the class teacher of any class this school year."}</p>
      ) : (
        <>
          {day.note ? (
            <p className="mb-4">{day.note}</p>
          ) : (
            <p className="mb-4 font-medium">
              {taken} of {day.rows.length} register{day.rows.length === 1 ? "" : "s"} taken.
            </p>
          )}
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">Registers on {formatDay(date)}</caption>
              <thead>
                <tr>
                  <th scope="col" className={thClass}>Class</th>
                  <th scope="col" className={thClass}>Register</th>
                </tr>
              </thead>
              <tbody>
                {day.rows.map((row) => (
                  <tr key={row.id}>
                    <th scope="row" className={`${tdClass} font-medium`}>
                      {day.note ? (
                        row.name
                      ) : (
                        <Link href={registerPath(row.id, date)} className="underline">
                          {row.name}
                        </Link>
                      )}
                    </th>
                    {/* One column, so the table fits a phone screen. */}
                    <td className={tdClass}>
                      {row.taken
                        ? `Taken: present ${row.present}, absent ${row.absent}, late ${row.late}`
                        : "Not taken"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
