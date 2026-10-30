"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import type { AcademicYearList } from "@/lib/academic-years";
import {
  classMarksPath,
  describeMarksError,
  formatScore,
  hasAnyMarksAccess,
  type ClassMarks,
  type OverviewMark,
} from "@/lib/assessments";
import { SCALE_NAMES, type TermResult } from "@/lib/grading";

// A class's marks for one term, every subject (D4): for school
// administrators, principals and the class teacher.

export function ClassMarksOverview() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} classId={id} />}</AppShell>;
}

function Content({ me, classId }: { me: Me; classId: string }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Marks overview</h1>
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
  return <Overview key={school.id} classId={classId} />;
}

function Overview({ classId }: { classId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const asked = Number(searchParams.get("term"));
  const [term, setTerm] = useState<number | null>(asked >= 1 && asked <= 3 ? asked : null);
  const [marks, setMarks] = useState<ClassMarks | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Without a term in the address: today's term, else Term 1.
  useEffect(() => {
    if (term !== null) {
      return;
    }
    let cancelled = false;
    api<AcademicYearList>("/school/academic-years").then((response) => {
      if (!cancelled) {
        setTerm(response.ok ? (response.data.current.term_number ?? 1) : 1);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [term]);

  useEffect(() => {
    if (term === null) {
      return;
    }
    let cancelled = false;
    api<ClassMarks>(`/school/classes/${classId}/marks?${new URLSearchParams({ term: String(term) })}`).then(
      (response) => {
        if (cancelled) {
          return;
        }
        if (response.status === 401) {
          goToLogin(classMarksPath(classId, term));
        } else if (response.status === 404) {
          setNotFound(true);
        } else if (response.ok) {
          setError(null);
          setMarks(response.data);
        } else {
          setMarks(null);
          setError(response.status === 422 ? describeMarksError(422, response.error) : withReference(response.error));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [classId, term]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Marks not found</h1>
        <p>
          This class does not exist, or you are not its class teacher.{" "}
          <Link href="/classes" className="underline">
            Back to the classes
          </Link>
          .
        </p>
      </section>
    );
  }

  // Each subject's assessments, then its term result (D5).
  const columns: Column[] = marks
    ? marks.subjects.flatMap((s): Column[] =>
        s.assessments.length === 0
          ? []
          : [
              ...s.assessments.map(
                (a): Column => ({ kind: "assessment", key: a.id, subject: s.subject.name, assessment: a }),
              ),
              { kind: "term", key: `term-${s.subject.id}`, subject: s.subject.name, results: s.term_results },
            ],
      )
    : [];

  return (
    <>
      <p className="mb-2">
        <Link href={`/classes/${classId}`} className="text-sm underline">
          Back to {marks?.class.name ?? "the class"}
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">Marks overview</h1>
          {marks && <p className="text-zinc-600 dark:text-zinc-400">{marks.class.name}</p>}
        </div>
        {term !== null && (
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
                setTerm(next);
                router.replace(classMarksPath(classId, next));
              }}
            >
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  Term {n}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <ErrorMessage message={error} />

      {!marks ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : columns.length === 0 ? (
        <p>No assessments in Term {marks.term.number} yet.</p>
      ) : marks.students.length === 0 ? (
        <p>No students in {marks.class.name} yet.</p>
      ) : (
        <>
          <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">
            Each mark with its percentage and grade on the{" "}
            <Link href="/grading" className="underline">
              {SCALE_NAMES[marks.scale.kind]}
            </Link>
            . A subject&apos;s term total adds up the assessments each student sat. Scroll the table sideways to see
            every assessment.
          </p>
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">
                Marks in {marks.class.name}, Term {marks.term.number}
              </caption>
              <thead>
                <tr>
                  <th scope="col" className={thClass}>Student</th>
                  {columns.map((column) =>
                    column.kind === "assessment" ? (
                      <th key={column.key} scope="col" className={thClass}>
                        <Link href={`/assessments/${column.assessment.id}`} className="underline underline-offset-4">
                          {column.subject}: {column.assessment.name}
                        </Link>
                        <span className="block font-normal text-zinc-600 dark:text-zinc-400">
                          out of {column.assessment.max_score}
                        </span>
                      </th>
                    ) : (
                      <th key={column.key} scope="col" className={thClass}>
                        {column.subject}: Term {marks.term.number}{" "}
                        <span className="block font-normal text-zinc-600 dark:text-zinc-400">total</span>
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {marks.students.map((student) => (
                  <tr key={student.id}>
                    <th scope="row" className={`${tdClass} font-medium`}>
                      {student.full_name}
                      <span className="block font-normal text-zinc-600 dark:text-zinc-400">
                        {student.admission_number}
                        {!student.in_class && ", no longer in this class"}
                      </span>
                    </th>
                    {columns.map((column) => (
                      <td key={column.key} className={tdClass}>
                        {column.kind === "assessment" ? (
                          <Cell mark={column.assessment.marks[student.id]} />
                        ) : (
                          <TermCell result={column.results[student.id]} />
                        )}
                      </td>
                    ))}
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

type Column =
  | { kind: "assessment"; key: string; subject: string; assessment: ClassMarks["subjects"][number]["assessments"][number] }
  | { kind: "term"; key: string; subject: string; results: Record<string, TermResult> };

function Cell({ mark }: { mark: OverviewMark | undefined }) {
  if (!mark) {
    return <span className="text-zinc-600 dark:text-zinc-400">Not entered</span>;
  }
  if (mark.did_not_sit || mark.score === null || !mark.result) {
    return <>Did not sit</>;
  }
  return (
    <>
      {formatScore(mark.score)} <span className="text-zinc-600 dark:text-zinc-400">({mark.result.percent}%)</span>{" "}
      <span className="font-medium">{mark.result.grade}</span>
    </>
  );
}

function TermCell({ result }: { result: TermResult | undefined }) {
  if (!result) {
    return <span className="text-zinc-600 dark:text-zinc-400">—</span>;
  }
  return (
    <>
      {formatScore(result.score)} / {result.max_score}{" "}
      <span className="text-zinc-600 dark:text-zinc-400">({result.percent}%)</span>{" "}
      <span className="font-medium">{result.grade}</span>
    </>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 align-bottom font-medium whitespace-nowrap dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top whitespace-nowrap dark:border-zinc-800";
