"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import type { AcademicYear, AcademicYearList } from "@/lib/academic-years";
import { canSeeFees, feesPath, formatKes, gradeFeesPath, type TermFees } from "@/lib/fees";

// School fees for one term (E1): every grade with classes that year, its
// fee structure and how many of its students are billed.

const PATH = "/fees";

export function Fees() {
  return <AppShell path={PATH}>{(me) => <Content me={me} />}</AppShell>;
}

export function NoFeesAccess({ me, title }: { me: Me; title: string }) {
  const school = me.active_school;
  return (
    <section>
      <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">{title}</h1>
      <p>
        {school ? `You do not have access to this page in ${school.name}.` : "Choose a school first."}{" "}
        <Link href="/" className="text-link underline underline-offset-2">
          Go to the home page
        </Link>
        .
      </p>
    </section>
  );
}

function Content({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Fees" />;
  }
  return <TermPicker key={school.id} />;
}

function TermPicker() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [list, setList] = useState<AcademicYearList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<AcademicYearList>("/school/academic-years").then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(PATH);
      } else if (response.ok) {
        setList(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!list) {
    return (
      <>
        <h1 className="mb-6 text-[1.9375rem] leading-tight font-bold tracking-tight">Fees</h1>
        <ErrorMessage message={error} />
        {!error && <p className="text-muted">Loading...</p>}
      </>
    );
  }
  const years = list.academic_years.filter((year) => year.terms.length > 0);
  if (years.length === 0) {
    return (
      <>
        <h1 className="mb-6 text-[1.9375rem] leading-tight font-bold tracking-tight">Fees</h1>
        <p>
          No school year with terms yet. Fees are set per term: an administrator sets up the year on the{" "}
          <Link href="/school-year" className="text-link underline underline-offset-2">
            School year
          </Link>{" "}
          page first.
        </p>
      </>
    );
  }

  // The year and term in the address, or else today's, or else the newest
  // year's first term.
  const askedYear = years.find((year) => year.id === searchParams.get("year"));
  const current = years.find((year) => year.id === list.current.academic_year_id);
  const year = askedYear ?? current ?? years[0];
  const askedTerm = Number(searchParams.get("term"));
  const todaysTerm = year.id === list.current.academic_year_id ? list.current.term_number : null;
  const term =
    year.terms.find((t) => t.number === askedTerm)?.number ??
    year.terms.find((t) => t.number === todaysTerm)?.number ??
    year.terms[0].number;

  function choose(next: AcademicYear, number: number) {
    const valid = next.terms.find((t) => t.number === number)?.number ?? next.terms[0].number;
    router.replace(feesPath(next.id, valid));
  }

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight">Fees</h1>
        <div className="flex flex-wrap gap-3">
          <div>
            <label htmlFor="year" className={labelClass}>
              School year
            </label>
            <select
              id="year"
              className={inputClass}
              value={year.id}
              onChange={(event) => choose(years.find((y) => y.id === event.target.value) ?? year, term)}
            >
              {years.map((y) => (
                <option key={y.id} value={y.id}>
                  {y.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="term" className={labelClass}>
              Term
            </label>
            <select
              id="term"
              className={inputClass}
              value={term}
              onChange={(event) => choose(year, Number(event.target.value))}
            >
              {year.terms.map((t) => (
                <option key={t.number} value={t.number}>
                  Term {t.number}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <TermTable key={`${year.id}/${term}`} yearId={year.id} term={term} />
    </>
  );
}

function TermTable({ yearId, term }: { yearId: string; term: number }) {
  const [data, setData] = useState<TermFees | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<TermFees>(`/school/fees/years/${yearId}/terms/${term}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(feesPath(yearId, term));
      } else if (response.ok) {
        setData(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [yearId, term]);

  if (!data) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }
  if (data.grades.length === 0) {
    return (
      <p>
        There are no classes in {data.year.name} yet. Fees are set for the grades that have classes.
      </p>
    );
  }
  return (
    <>
      <p className="mb-4 max-w-2xl text-sm text-muted">
        Each grade has one fee structure per term.{" "}
        {data.can_manage
          ? "Open a grade to set its fees and issue bills to its students."
          : "Open a grade to see its fees and bills."}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Fees for Term {data.term.number}, {data.year.name}
          </caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>
                Grade
              </th>
              <th scope="col" className={thClass}>
                Fee structure
              </th>
              <th scope="col" className={`${thClass} ${amountClass}`}>
                Compulsory fees
              </th>
              <th scope="col" className={thClass}>
                Students billed
              </th>
            </tr>
          </thead>
          <tbody>
            {data.grades.map((row) => (
              <tr key={row.grade}>
                <th scope="row" className={`${tdClass} font-normal`}>
                  <Link href={gradeFeesPath(yearId, term, row.grade)} className="font-medium text-link underline underline-offset-2">
                    {row.name}
                    <span className="sr-only"> fees</span>
                  </Link>
                </th>
                <td className={tdClass}>
                  {!row.structure
                    ? "Not set"
                    : `${row.structure.issued ? "Issued" : "Draft"}, ${row.structure.items} item${row.structure.items === 1 ? "" : "s"}`}
                </td>
                <td className={`${tdClass} ${amountClass}`}>{row.structure ? formatKes(row.structure.compulsory_total_kes) : "—"}</td>
                <td className={tdClass}>
                  {row.billed} of {row.students}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export const thClass = "border-b border-rule-strong px-2 py-2 font-medium";
// Money: right-aligned so the figures line up, and never split over two lines.
export const amountClass = "text-right whitespace-nowrap";
export const tdClass = "border-b border-rule px-2 py-2";
