"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import type { AcademicYearList } from "@/lib/academic-years";
import { classMarksPath, describeMarksError, hasAnyMarksAccess } from "@/lib/assessments";
import { SCALE_NAMES, type TermResult } from "@/lib/grading";
import { classResultsPath, type ClassResults, type Overall } from "@/lib/results";

// A class's term results (D6): each subject's result, the overall result
// and, when the school shows them, class positions. For school
// administrators, principals and the class teacher.

export function ClassResultsPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} classId={id} />}</AppShell>;
}

function Content({ me, classId }: { me: Me; classId: string }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Term results</h1>
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
  return <Results key={school.id} classId={classId} />;
}

function Results({ classId }: { classId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const asked = Number(searchParams.get("term"));
  const [term, setTerm] = useState<number | null>(asked >= 1 && asked <= 3 ? asked : null);
  const [results, setResults] = useState<ClassResults | null>(null);
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
    api<ClassResults>(`/school/classes/${classId}/results?${new URLSearchParams({ term: String(term) })}`).then(
      (response) => {
        if (cancelled) {
          return;
        }
        if (response.status === 401) {
          goToLogin(classResultsPath(classId, term));
        } else if (response.status === 404) {
          setNotFound(true);
        } else if (response.ok) {
          setError(null);
          setResults(response.data);
        } else {
          setResults(null);
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
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Results not found</h1>
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

  const kcse = results?.scale.kind === "kcse";

  return (
    <>
      <p className="mb-2 flex flex-wrap gap-x-4">
        <Link href={`/classes/${classId}`} className="text-sm underline">
          Back to {results?.class.name ?? "the class"}
        </Link>
        {term !== null && (
          <Link href={classMarksPath(classId, term)} className="text-sm underline">
            Marks overview
          </Link>
        )}
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">Term results</h1>
          {results && <p className="text-zinc-600 dark:text-zinc-400">{results.class.name}</p>}
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
                router.replace(classResultsPath(classId, next));
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

      {!results ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : results.subjects.length === 0 ? (
        <p>No assessments in Term {results.term.number} yet.</p>
      ) : results.students.length === 0 ? (
        <p>No students in {results.class.name} yet.</p>
      ) : (
        <>
          <p className="mb-3 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
            Each subject&apos;s term result on the{" "}
            <Link href="/grading" className="underline">
              {SCALE_NAMES[results.scale.kind]}
            </Link>
            .{" "}
            {kcse
              ? "The mean grade counts Mathematics, the best language and the best five other subjects."
              : "The overall result is the average of the subjects' points."}{" "}
            Scroll the table sideways to see every subject.
          </p>
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">
                Term {results.term.number} results in {results.class.name}
              </caption>
              <thead>
                <tr>
                  {results.show_positions && (
                    <th scope="col" className={thClass}>
                      Position
                    </th>
                  )}
                  <th scope="col" className={thClass}>
                    Student
                  </th>
                  <th scope="col" className={thClass}>
                    {kcse ? "Mean grade" : "Overall"}
                  </th>
                  {results.subjects.map((subject) => (
                    <th key={subject.id} scope="col" className={thClass}>
                      {subject.name}
                      {subject.weighted && (
                        <span className="block font-normal text-zinc-600 dark:text-zinc-400">weighted</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.students.map((student) => (
                  <tr key={student.id}>
                    {results.show_positions && (
                      <td className={tdClass}>{student.position ?? <span className="text-zinc-600 dark:text-zinc-400">—</span>}</td>
                    )}
                    <th scope="row" className={`${tdClass} font-medium`}>
                      {student.full_name}
                      <span className="block font-normal text-zinc-600 dark:text-zinc-400">
                        {student.admission_number}
                        {!student.in_class && ", no longer in this class"}
                      </span>
                    </th>
                    <td className={tdClass}>
                      <OverallCell overall={student.overall} />
                    </td>
                    {results.subjects.map((subject) => (
                      <td key={subject.id} className={tdClass}>
                        <SubjectCell result={student.results[subject.id]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {results.show_positions && (
            <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
              Positions go to complete results only; students with the same points share a place.
            </p>
          )}
        </>
      )}
    </>
  );
}

function OverallCell({ overall }: { overall: Overall | null }) {
  if (!overall) {
    return <span className="text-zinc-600 dark:text-zinc-400">—</span>;
  }
  const detail = `${overall.total_points} points, ${overall.subjects_counted} subject${overall.subjects_counted === 1 ? "" : "s"}`;
  return (
    <>
      <span className="font-medium">{overall.grade}</span>
      {!overall.complete && <span className="ml-1 font-medium">(incomplete)</span>}
      <span className="block text-zinc-600 dark:text-zinc-400">{detail}</span>
    </>
  );
}

function SubjectCell({ result }: { result: TermResult | undefined }) {
  if (!result) {
    return <span className="text-zinc-600 dark:text-zinc-400">—</span>;
  }
  return (
    <>
      {result.percent}% <span className="font-medium">{result.grade}</span>
    </>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 align-bottom font-medium whitespace-nowrap dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top whitespace-nowrap dark:border-zinc-800";
