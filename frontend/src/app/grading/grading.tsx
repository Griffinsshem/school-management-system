"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { describeMarksError, hasAnyMarksAccess } from "@/lib/assessments";
import { SCALE_NAMES, canManageGrading, type Band, type Grading } from "@/lib/grading";

// The school's grading scales (D5): the fixed CBC/KJSEA bands, and the KCSE
// boundaries school administrators may change. Everyone who sees marks can
// read this page.

const PATH = "/grading";
const GRADING = "/school/grading";

export function GradingPage() {
  return <AppShell path={PATH}>{(me) => <Content me={me} />}</AppShell>;
}

function Content({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Grading</h1>
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
  return <Scales key={school.id} schoolName={school.name} canManage={canManageGrading(me)} />;
}

function Scales({ schoolName, canManage }: { schoolName: string; canManage: boolean }) {
  const [grading, setGrading] = useState<Grading | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Grading>(GRADING).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(PATH);
      } else if (response.ok) {
        setGrading(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!grading) {
    return error ? <ErrorMessage message={error} /> : <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>;
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight">Grading</h1>
        <p className="text-zinc-600 dark:text-zinc-400">{schoolName}</p>
      </div>
      <p className="mb-6 max-w-2xl">
        Each mark is turned into a percentage, rounded to a whole number, and graded on its class&apos;s scale.
        Grades are worked out each time they are shown, so a change here regrades every mark at once.
      </p>
      {notice && <Notice>{notice}</Notice>}

      <section aria-labelledby="kcse-heading" className="mb-10">
        <h2 id="kcse-heading" className="mb-1 text-xl font-semibold">
          {SCALE_NAMES.kcse}
        </h2>
        <p className="mb-3 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
          For Form classes.{" "}
          {grading.kcse.is_default
            ? "These are the default boundaries, a common choice for school exams; KNEC sets its own for KCSE itself."
            : "This school has set its own boundaries."}
        </p>
        {editing ? (
          <KcseForm
            grading={grading}
            onSaved={(next) => {
              setGrading(next);
              setEditing(false);
              setNotice("Boundaries saved. Every Form mark is now graded with them.");
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <>
            <BandTable caption="KCSE grade boundaries" bands={grading.kcse.bands} />
            {canManage && (
              <button
                type="button"
                className={`${secondaryButtonClass} mt-4`}
                onClick={() => {
                  setNotice(null);
                  setEditing(true);
                }}
              >
                Change boundaries
              </button>
            )}
          </>
        )}
      </section>

      <Positions
        shown={grading.show_class_positions}
        canManage={canManage}
        onSaved={(next, message) => {
          setGrading(next);
          setNotice(message);
        }}
      />

      <section aria-labelledby="cbc-heading">
        <h2 id="cbc-heading" className="mb-1 text-xl font-semibold">
          {SCALE_NAMES.cbc}
        </h2>
        <p className="mb-3 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
          For PP1 to Grade 12: the eight KJSEA performance levels published by KNEC. It cannot be changed.
        </p>
        <BandTable caption="CBC performance levels" bands={grading.cbc.bands} />
      </section>
    </>
  );
}

// Whether results pages rank students (D6): off unless an administrator
// switches it on.
function Positions({
  shown,
  canManage,
  onSaved,
}: {
  shown: boolean;
  canManage: boolean;
  onSaved: (grading: Grading, message: string) => void;
}) {
  const [checked, setChecked] = useState(shown);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const response = await api<Grading>(`${GRADING}/positions`, {
      method: "PUT",
      body: { show_class_positions: checked },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(PATH);
    } else if (response.ok) {
      onSaved(
        response.data,
        response.data.show_class_positions
          ? "Class positions are now shown on term results."
          : "Class positions are now hidden.",
      );
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <section aria-labelledby="positions-heading" className="mb-10">
      <h2 id="positions-heading" className="mb-1 text-xl font-semibold">
        Class positions
      </h2>
      <p className="mb-3 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
        Term results can rank students within their class. Kenya no longer ranks candidates in national exams,
        so this is off unless the school chooses it.
      </p>
      {canManage ? (
        <form onSubmit={onSubmit} noValidate>
          <ErrorMessage message={error} />
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4"
              checked={checked}
              onChange={(event) => setChecked(event.target.checked)}
            />
            <span>Show class positions on term results</span>
          </label>
          <button type="submit" className={`${secondaryButtonClass} mt-3`} disabled={pending || checked === shown}>
            {pending ? "Saving..." : "Save"}
          </button>
        </form>
      ) : (
        <p className="text-sm font-medium">
          {shown ? "Term results show class positions." : "Term results do not show class positions."}
        </p>
      )}
    </section>
  );
}

function BandTable({ caption, bands }: { caption: string; bands: Band[] }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full max-w-md border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>Grade</th>
            <th scope="col" className={thClass}>Percentage</th>
            <th scope="col" className={thClass}>Points</th>
          </tr>
        </thead>
        <tbody>
          {bands.map((band, index) => (
            <tr key={band.grade}>
              <th scope="row" className={`${tdClass} font-medium`}>
                {band.grade}
              </th>
              <td className={tdClass}>
                {band.min_percent} to {index === 0 ? 100 : bands[index - 1].min_percent - 1}
              </td>
              <td className={tdClass}>{band.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KcseForm({
  grading,
  onSaved,
  onCancel,
}: {
  grading: Grading;
  onSaved: (grading: Grading) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(grading.kcse.bands.map((b) => [b.grade, String(b.min_percent)])),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const grades = grading.kcse.bands.map((b) => b.grade);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const wrong = grades.filter((g) => !/^\d{1,3}$/.test(values[g].trim()) || Number(values[g]) > 100);
    if (wrong.length > 0) {
      setError(`Use a whole number from 0 to 100 for ${wrong.join(", ")}.`);
      return;
    }
    const boundaries = Object.fromEntries(grades.map((g) => [g, Number(values[g])]));
    setPending(true);
    const response = await api<Grading>(`${GRADING}/kcse`, { method: "PUT", body: { boundaries } });
    setPending(false);
    if (response.status === 401) {
      goToLogin(PATH);
    } else if (response.ok) {
      onSaved(response.data);
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="max-w-md">
      <ErrorMessage message={error} />
      <p className="mb-3 text-sm">
        The lowest percentage for each grade. Each must be higher than the one below it, and E starts at 0.
      </p>
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
        {grades.map((grade) => (
          <label key={grade} className="text-sm font-medium">
            {grade}
            <input
              aria-label={`Lowest percentage for ${grade}`}
              inputMode="numeric"
              autoComplete="off"
              className={`${inputClass} mt-1`}
              value={values[grade]}
              onChange={(e) => setValues((current) => ({ ...current, [grade]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="submit" className={inlineButtonClass} disabled={pending}>
          {pending ? "Saving..." : "Save boundaries"}
        </button>
        <button
          type="button"
          className={secondaryButtonClass}
          disabled={pending}
          onClick={() => setValues(Object.fromEntries(grades.map((g) => [g, String(grading.default_kcse[g])])))}
        >
          Fill in the defaults
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
