"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { formatCalendarDate } from "@/lib/academic-years";
import {
  MAX_ASSESSMENT_NAME,
  MAX_SCORE_LIMIT,
  describeMarksError,
  formatScore,
  hasAnyMarksAccess,
  parseScore,
  percent,
  subjectMarksPath,
  type MarkSheet,
  type SheetStudent,
} from "@/lib/assessments";

// One assessment's marks: entered by its subject teacher (or a school
// administrator), read by the class teacher and the principal (D4).

export function MarkSheetPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} assessmentId={id} />}</AppShell>;
}

function Content({ me, assessmentId }: { me: Me; assessmentId: string }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Mark sheet</h1>
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
  return <Sheet key={school.id} assessmentId={assessmentId} />;
}

function Sheet({ assessmentId }: { assessmentId: string }) {
  const router = useRouter();
  const path = `/school/assessments/${assessmentId}`;
  const [sheet, setSheet] = useState<MarkSheet | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<MarkSheet>(`${path}/marks`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(`/assessments/${assessmentId}`);
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setSheet(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, assessmentId, version]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Assessment not found</h1>
        <p>
          This assessment does not exist, or it is not one of yours.{" "}
          <Link href="/classes" className="underline">
            Back to the classes
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!sheet) {
    return error ? <ErrorMessage message={error} /> : <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>;
  }

  const { assessment } = sheet;
  const editable = sheet.can_record && (!assessment.is_locked || sheet.can_lock);
  const back = subjectMarksPath(sheet.class.id, sheet.subject.id, assessment.term);

  async function setLock(lock: boolean) {
    setError(null);
    setNotice(null);
    setBusy(true);
    const response = await api<MarkSheet>(`${path}/${lock ? "lock" : "unlock"}`, { method: "POST" });
    setBusy(false);
    if (response.status === 401) {
      goToLogin(`/assessments/${assessmentId}`);
    } else if (response.ok) {
      setSheet(response.data);
      setNotice(lock ? "Locked: only school administrators can change these marks now." : "Unlocked.");
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  async function remove() {
    setError(null);
    setBusy(true);
    const response = await api(path, { method: "DELETE" });
    setBusy(false);
    if (response.status === 401) {
      goToLogin(`/assessments/${assessmentId}`);
    } else if (response.ok) {
      router.push(back);
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <>
      <p className="mb-2">
        <Link href={back} className="text-sm underline">
          Back to {sheet.subject.name} marks
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">{assessment.name}</h1>
          <p className="text-zinc-600 dark:text-zinc-400">
            {sheet.subject.name}, {sheet.class.name}, Term {assessment.term}
          </p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Done on {formatCalendarDate(assessment.held_on)}, out of {assessment.max_score}
          </p>
          {assessment.is_locked && (
            <p className="mt-1 text-sm font-medium">Locked: only school administrators can change these marks.</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {editable && !editingDetails && (
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => {
                setNotice(null);
                setEditingDetails(true);
              }}
              disabled={busy}
            >
              Edit details
            </button>
          )}
          {sheet.can_lock && (
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => setLock(!assessment.is_locked)}
              disabled={busy}
            >
              {assessment.is_locked ? "Unlock" : "Lock"}
            </button>
          )}
        </div>
      </div>

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {editingDetails && (
        <DetailsForm
          path={path}
          sheet={sheet}
          onSaved={() => {
            setEditingDetails(false);
            setNotice("Details saved.");
            setVersion((v) => v + 1);
          }}
          onDelete={assessment.marks_entered === 0 ? remove : null}
          onCancel={() => setEditingDetails(false)}
        />
      )}

      {sheet.students.length === 0 ? (
        <p>No students in {sheet.class.name} yet.</p>
      ) : editable ? (
        <MarksForm
          key={`${version}-${assessment.is_locked}`}
          path={path}
          sheet={sheet}
          onSaved={(next, changed) => {
            setError(null);
            setSheet(next);
            setNotice(changed ? "Marks saved." : "Nothing had changed.");
          }}
        />
      ) : (
        <ReadOnlyMarks sheet={sheet} />
      )}
    </>
  );
}

type Row = { text: string; didNotSit: boolean };

function initialRows(students: SheetStudent[]): Record<string, Row> {
  return Object.fromEntries(
    students.map((s) => [s.id, { text: s.score === null ? "" : formatScore(s.score), didNotSit: s.did_not_sit }]),
  );
}

function label(student: SheetStudent): string {
  return `${student.full_name} (${student.admission_number})`;
}

function Summary({ scores, didNotSit, students, max }: { scores: number[]; didNotSit: number; students: number; max: number }) {
  const entered = scores.length + didNotSit;
  const average = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  return (
    <p className="mb-3 text-sm" aria-live="polite">
      {entered} of {students} entered
      {didNotSit > 0 && `, ${didNotSit} did not sit`}
      {average !== null && `. Average ${average.toFixed(1)} out of ${max} (${percent(average, max)})`}.
    </p>
  );
}

function MarksForm({
  path,
  sheet,
  onSaved,
}: {
  path: string;
  sheet: MarkSheet;
  onSaved: (sheet: MarkSheet, changed: boolean) => void;
}) {
  const max = sheet.assessment.max_score;
  const [rows, setRows] = useState<Record<string, Row>>(() => initialRows(sheet.students));
  const [problems, setProblems] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const parsed = sheet.students.map((s) => ({ student: s, row: rows[s.id], value: parseScore(rows[s.id].text, max) }));
  const scores = parsed.flatMap((p) => (!p.row.didNotSit && typeof p.value === "number" ? [p.value] : []));
  const didNotSit = parsed.filter((p) => p.row.didNotSit).length;

  function update(id: string, change: Partial<Row>) {
    setRows((current) => ({ ...current, [id]: { ...current[id], ...change } }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblems(null);
    const wrong = parsed.filter((p) => !p.row.didNotSit && p.value !== null && typeof p.value === "object");
    if (wrong.length > 0) {
      setProblems(
        wrong.map((p) => `${p.student.full_name}: ${(p.value as { error: string }).error}`).join(" "),
      );
      return;
    }
    // Only what changed is sent; everyone else keeps their mark.
    const marks = parsed.flatMap(({ student, row, value }) => {
      const score = row.didNotSit ? null : (value as number | null);
      if (score === student.score && row.didNotSit === student.did_not_sit) {
        return [];
      }
      return [{ student_id: student.id, score, did_not_sit: row.didNotSit }];
    });
    if (marks.length === 0) {
      onSaved(sheet, false);
      return;
    }
    setPending(true);
    const response = await api<MarkSheet>(`${path}/marks`, { method: "PUT", body: { marks } });
    setPending(false);
    if (response.status === 401) {
      goToLogin("/classes");
    } else if (response.ok) {
      setRows(initialRows(response.data.students));
      onSaved(response.data, true);
    } else {
      setProblems(describeMarksError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={save} noValidate>
      <Summary scores={scores} didNotSit={didNotSit} students={sheet.students.length} max={max} />
      <ErrorMessage message={problems} />
      <ul className="mb-4 divide-y divide-zinc-200 border-y border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {sheet.students.map((student) => {
          const row = rows[student.id];
          return (
            <li key={student.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2">
              <span>
                {student.full_name}{" "}
                <span className="text-zinc-600 dark:text-zinc-400">({student.admission_number})</span>
                {!student.in_class && (
                  <span className="text-zinc-600 dark:text-zinc-400"> (no longer in this class)</span>
                )}
              </span>
              <span className="flex items-center gap-3">
                <input
                  aria-label={`Score for ${label(student)}`}
                  inputMode="decimal"
                  autoComplete="off"
                  className={`${inputClass} w-24`}
                  value={row.didNotSit ? "" : row.text}
                  disabled={row.didNotSit}
                  onChange={(e) => update(student.id, { text: e.target.value })}
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={row.didNotSit}
                    onChange={(e) => update(student.id, { didNotSit: e.target.checked })}
                  />
                  Did not sit
                </label>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">
        Scores out of {max}, with at most one decimal place. Leave a box empty for a mark not entered yet.
      </p>
      <button type="submit" className={inlineButtonClass} disabled={pending}>
        {pending ? "Saving..." : "Save marks"}
      </button>
    </form>
  );
}

function ReadOnlyMarks({ sheet }: { sheet: MarkSheet }) {
  const max = sheet.assessment.max_score;
  const scores = sheet.students.flatMap((s) => (s.score === null ? [] : [s.score]));
  return (
    <>
      <Summary
        scores={scores}
        didNotSit={sheet.students.filter((s) => s.did_not_sit).length}
        students={sheet.students.length}
        max={max}
      />
      <div className="relative overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Marks</caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>Admission no.</th>
              <th scope="col" className={thClass}>Name</th>
              <th scope="col" className={thClass}>Score</th>
            </tr>
          </thead>
          <tbody>
            {sheet.students.map((s) => (
              <tr key={s.id}>
                <td className={tdClass}>{s.admission_number}</td>
                <td className={tdClass}>
                  {s.full_name}
                  {!s.in_class && <span className="text-zinc-600 dark:text-zinc-400"> (no longer in this class)</span>}
                </td>
                <td className={tdClass}>
                  {s.did_not_sit
                    ? "Did not sit"
                    : s.score === null
                      ? "Not entered"
                      : `${formatScore(s.score)} (${percent(s.score, max)})`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DetailsForm({
  path,
  sheet,
  onSaved,
  onDelete,
  onCancel,
}: {
  path: string;
  sheet: MarkSheet;
  onSaved: () => void;
  onDelete: (() => void) | null;
  onCancel: () => void;
}) {
  const { assessment } = sheet;
  const [name, setName] = useState(assessment.name);
  const [maxScore, setMaxScore] = useState(String(assessment.max_score));
  const [heldOn, setHeldOn] = useState(assessment.held_on);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const max = Number(maxScore);
    if (!name.trim()) {
      setError("Enter the assessment's name.");
      return;
    }
    if (!/^\d+$/.test(maxScore.trim()) || max < 1 || max > MAX_SCORE_LIMIT) {
      setError(`"Out of" must be a whole number from 1 to ${MAX_SCORE_LIMIT}.`);
      return;
    }
    const body: Record<string, string | number> = {};
    if (name.trim() !== assessment.name) {
      body.name = name;
    }
    if (max !== assessment.max_score) {
      body.max_score = max;
    }
    if (heldOn !== assessment.held_on) {
      body.held_on = heldOn;
    }
    if (Object.keys(body).length === 0) {
      onCancel();
      return;
    }
    setPending(true);
    const response = await api(path, { method: "PATCH", body });
    setPending(false);
    if (response.status === 401) {
      goToLogin("/classes");
    } else if (response.ok) {
      onSaved();
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <section
      aria-labelledby="details-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2 id="details-heading" ref={headingRef} tabIndex={-1} className="mb-4 text-xl font-semibold focus:outline-none">
        Edit {assessment.name}
      </h2>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="details-name" className={labelClass}>
              Name
            </label>
            <input
              id="details-name"
              autoComplete="off"
              maxLength={MAX_ASSESSMENT_NAME}
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="details-max" className={labelClass}>
              Out of
            </label>
            <input
              id="details-max"
              inputMode="numeric"
              autoComplete="off"
              className={inputClass}
              value={maxScore}
              onChange={(e) => setMaxScore(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="details-date" className={labelClass}>
              Date done
            </label>
            <input
              id="details-date"
              type="date"
              className={inputClass}
              value={heldOn}
              onChange={(e) => setHeldOn(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            Save details
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
          {onDelete && !confirming && (
            <button type="button" className={secondaryButtonClass} onClick={() => setConfirming(true)} disabled={pending}>
              Delete assessment
            </button>
          )}
        </div>
        {onDelete && confirming && (
          <div className="mt-4 flex flex-col gap-2">
            <span>Delete {assessment.name}? It has no marks yet.</span>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
                onClick={onDelete}
                disabled={pending}
              >
                Yes, delete
              </button>
              <button type="button" className={`${secondaryButtonClass} py-1`} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </form>
    </section>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
