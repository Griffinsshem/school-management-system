"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { formatCalendarDate } from "@/lib/academic-years";
import {
  MAX_ASSESSMENT_NAME,
  MAX_SCORE_LIMIT,
  defaultTerm,
  describeMarksError,
  hasAnyMarksAccess,
  subjectMarksPath,
  type Assessment,
  type AssessmentList,
  type AssessmentTerm,
} from "@/lib/assessments";
import { kenyaToday } from "@/lib/attendance";

// A subject's assessments in one class, for one term (D4).

export function SubjectMarks() {
  const { id, subjectId } = useParams<{ id: string; subjectId: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} classId={id} subjectId={subjectId} />}</AppShell>;
}

function Content({ me, classId, subjectId }: { me: Me; classId: string; subjectId: string }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Marks</h1>
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
  return <Assessments key={school.id} classId={classId} subjectId={subjectId} />;
}

function Assessments({ classId, subjectId }: { classId: string; subjectId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const path = `/school/classes/${classId}/subjects/${subjectId}/assessments`;
  const [list, setList] = useState<AssessmentList | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<AssessmentList>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(subjectMarksPath(classId, subjectId));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setList(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, classId, subjectId, version]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Marks not found</h1>
        <p>
          This class or subject does not exist, or it is not one of yours.{" "}
          <Link href="/classes" className="underline">
            Back to the classes
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!list) {
    return error ? <ErrorMessage message={error} /> : <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>;
  }

  const asked = Number(searchParams.get("term"));
  const term = list.terms.find((t) => t.number === asked)?.number ?? defaultTerm(list.terms, kenyaToday());
  const current = list.terms.find((t) => t.number === term);
  const shown = list.assessments.filter((a) => a.term === term);
  const title = `${list.subject.name} marks`;

  return (
    <>
      <p className="mb-2">
        <Link href={`/classes/${classId}`} className="text-sm underline">
          Back to {list.class.name}
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="text-zinc-600 dark:text-zinc-400">{list.class.name}</p>
        </div>
        {list.terms.length > 0 && term !== null && (
          <div>
            <label htmlFor="term" className={labelClass}>
              Term
            </label>
            <select
              id="term"
              className={inputClass}
              value={term}
              onChange={(event) => {
                setAdding(false);
                setNotice(null);
                router.replace(subjectMarksPath(classId, subjectId, Number(event.target.value)));
              }}
            >
              {list.terms.map((t) => (
                <option key={t.number} value={t.number}>
                  Term {t.number}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {!current ? (
        <p>This school year has no terms yet, so no assessments can be added.</p>
      ) : (
        <>
          {list.can_record && !adding && (
            <div className="mb-6">
              <button
                type="button"
                className={inlineButtonClass}
                onClick={() => {
                  setNotice(null);
                  setAdding(true);
                }}
              >
                Add an assessment
              </button>
            </div>
          )}
          {adding && (
            <AddAssessment
              path={path}
              term={current}
              onAdded={(name) => {
                setAdding(false);
                setNotice(`Added ${name}. Open it to enter marks.`);
                setVersion((v) => v + 1);
              }}
              onCancel={() => setAdding(false)}
            />
          )}
          {shown.length === 0 ? (
            <p>No assessments in Term {current.number} yet.</p>
          ) : (
            <AssessmentTable assessments={shown} students={list.students} />
          )}
        </>
      )}
    </>
  );
}

function AssessmentTable({ assessments, students }: { assessments: Assessment[]; students: number }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Assessments</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>Assessment</th>
            <th scope="col" className={thClass}>Date</th>
            <th scope="col" className={thClass}>Out of</th>
            <th scope="col" className={thClass}>Marks</th>
          </tr>
        </thead>
        <tbody>
          {assessments.map((a) => (
            <tr key={a.id}>
              <th scope="row" className={`${tdClass} font-medium`}>
                <Link href={`/assessments/${a.id}`} className="underline underline-offset-4 hover:no-underline">
                  {a.name}
                </Link>
                {a.is_locked && <span className="ml-2 text-zinc-600 dark:text-zinc-400">(locked)</span>}
              </th>
              <td className={tdClass}>{formatCalendarDate(a.held_on)}</td>
              <td className={tdClass}>{a.max_score}</td>
              <td className={tdClass}>
                {a.marks_entered} of {students}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddAssessment({
  path,
  term,
  onAdded,
  onCancel,
}: {
  path: string;
  term: AssessmentTerm;
  onAdded: (name: string) => void;
  onCancel: () => void;
}) {
  const today = kenyaToday();
  const [name, setName] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [heldOn, setHeldOn] = useState(today <= term.ends_on && today >= term.starts_on ? today : "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const latest = today < term.ends_on ? today : term.ends_on;

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const max = Number(maxScore);
    if (!name.trim()) {
      setError("Enter the assessment's name, such as Mid-term.");
      return;
    }
    if (!/^\d+$/.test(maxScore.trim()) || max < 1 || max > MAX_SCORE_LIMIT) {
      setError(`"Out of" must be a whole number from 1 to ${MAX_SCORE_LIMIT}.`);
      return;
    }
    if (!heldOn) {
      setError("Choose the date it was done.");
      return;
    }
    setPending(true);
    const response = await api<{ assessment: Assessment }>(path, {
      method: "POST",
      body: { term: term.number, name, max_score: max, held_on: heldOn },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin("/classes");
    } else if (response.ok) {
      onAdded(response.data.assessment.name);
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <section
      aria-labelledby="add-assessment-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2
        id="add-assessment-heading"
        ref={headingRef}
        tabIndex={-1}
        className="mb-4 text-xl font-semibold focus:outline-none"
      >
        Add an assessment to Term {term.number}
      </h2>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="assessment-name" className={labelClass}>
              Name <span className="font-normal">(for example Mid-term)</span>
            </label>
            <input
              id="assessment-name"
              autoComplete="off"
              maxLength={MAX_ASSESSMENT_NAME}
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="assessment-max" className={labelClass}>
              Out of
            </label>
            <input
              id="assessment-max"
              inputMode="numeric"
              autoComplete="off"
              className={inputClass}
              value={maxScore}
              onChange={(e) => setMaxScore(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="assessment-date" className={labelClass}>
              Date done
            </label>
            <input
              id="assessment-date"
              type="date"
              min={term.starts_on}
              max={latest}
              className={inputClass}
              value={heldOn}
              onChange={(e) => setHeldOn(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Saving..." : "Add assessment"}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
