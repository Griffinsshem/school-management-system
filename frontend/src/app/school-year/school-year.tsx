"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import {
  ErrorMessage,
  Notice,
  inlineButtonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
} from "@/components/ui";
import { api, withReference, type ApiErrorBody, type Me } from "@/lib/api";
import {
  EARLIEST_DATE,
  LATEST_DATE,
  MAX_YEAR_NAME,
  TERM_NUMBERS,
  describeToday,
  formatCalendarDate,
  type AcademicYear,
  type AcademicYearList,
} from "@/lib/academic-years";

const PATH = "/school-year";
const YEARS = "/school/academic-years";

export function SchoolYear() {
  return <AppShell path={PATH}>{(me) => <SchoolYearContent me={me} />}</AppShell>;
}

function SchoolYearContent({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">School year</h1>
        <p>
          Choose a school first on the{" "}
          <Link href="/" className="underline">
            home page
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!me.permissions.includes("academics.read")) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">School year</h1>
        <p>You do not have access to this page in {school.name}.</p>
      </section>
    );
  }
  // Keyed by school, so switching school starts this page afresh.
  return (
    <Years
      key={school.id}
      schoolName={school.name}
      canManage={me.permissions.includes("academics.manage")}
    />
  );
}

// The form that is open, if any. Only one at a time.
type Editing =
  | { mode: "add" }
  | { mode: "year"; year: AcademicYear }
  | { mode: "term"; year: AcademicYear; number: number }
  | null;

function Years({ schoolName, canManage }: { schoolName: string; canManage: boolean }) {
  const [list, setList] = useState<AcademicYearList | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  useEffect(() => {
    let cancelled = false;
    api<AcademicYearList>(YEARS).then((response) => {
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
  }, [version]);

  function open(next: Editing) {
    setError(null);
    setNotice(null);
    setEditing(next);
  }

  function saved(message: string) {
    setEditing(null);
    setNotice(message);
    setVersion((current) => current + 1);
  }

  const current = list?.current;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">School year</h1>
          <p className="text-zinc-600 dark:text-zinc-400">{schoolName}</p>
        </div>
        {canManage && !editing && list && (
          <button type="button" className={inlineButtonClass} onClick={() => open({ mode: "add" })}>
            Add a school year
          </button>
        )}
      </div>

      {editing?.mode === "add" && <AddYearForm onSaved={saved} onCancel={() => setEditing(null)} />}
      {editing?.mode === "year" && (
        <EditYearForm year={editing.year} onSaved={saved} onCancel={() => setEditing(null)} />
      )}
      {editing?.mode === "term" && (
        <TermForm
          year={editing.year}
          number={editing.number}
          onSaved={saved}
          onCancel={() => setEditing(null)}
        />
      )}

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {!list ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : (
        <>
          <section
            aria-labelledby="today-heading"
            className="mb-8 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950"
          >
            <h2 id="today-heading" className="mb-1 text-sm font-medium">
              Today
            </h2>
            <p>{describeToday(list)}</p>
          </section>

          {list.academic_years.map((year) => (
            <YearSection
              key={year.id}
              year={year}
              isCurrent={current?.academic_year_id === year.id}
              currentTerm={current?.academic_year_id === year.id ? current.term_number : null}
              canManage={canManage}
              busy={editing !== null}
              onEditYear={() => open({ mode: "year", year })}
              onEditTerm={(number) => open({ mode: "term", year, number })}
            />
          ))}
        </>
      )}
    </>
  );
}

function YearSection({
  year,
  isCurrent,
  currentTerm,
  canManage,
  busy,
  onEditYear,
  onEditTerm,
}: {
  year: AcademicYear;
  isCurrent: boolean;
  currentTerm: number | null;
  canManage: boolean;
  busy: boolean;
  onEditYear: () => void;
  onEditTerm: (number: number) => void;
}) {
  const headingId = `year-${year.id}`;
  return (
    <section aria-labelledby={headingId} className="mb-8">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id={headingId} className="text-xl font-semibold">
            {year.name}
            {isCurrent && <CurrentBadge />}
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {formatCalendarDate(year.starts_on)} to {formatCalendarDate(year.ends_on)}
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            className={`${secondaryButtonClass} py-1`}
            aria-label={`Edit the school year ${year.name}`}
            onClick={onEditYear}
            disabled={busy}
          >
            Edit year
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Terms of {year.name}</caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>Term</th>
              <th scope="col" className={thClass}>Starts</th>
              <th scope="col" className={thClass}>Ends</th>
              {canManage && (
                <th scope="col" className={thClass}>
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {TERM_NUMBERS.map((number) => {
              const term = year.terms.find((t) => t.number === number);
              return (
                <tr key={number}>
                  <th scope="row" className={`${tdClass} font-normal`}>
                    Term {number}
                    {currentTerm === number && <CurrentBadge />}
                  </th>
                  <td className={tdClass}>{term ? formatCalendarDate(term.starts_on) : "Not set"}</td>
                  <td className={tdClass}>{term ? formatCalendarDate(term.ends_on) : "-"}</td>
                  {canManage && (
                    <td className={tdClass}>
                      <button
                        type="button"
                        className={`${secondaryButtonClass} py-1`}
                        aria-label={`${term ? "Change" : "Set"} the dates of Term ${number} of ${year.name}`}
                        onClick={() => onEditTerm(number)}
                        disabled={busy}
                      >
                        {term ? "Change" : "Set dates"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CurrentBadge() {
  return (
    <span className="ml-2 rounded bg-blue-700 px-1.5 py-0.5 align-middle text-xs font-medium text-white">
      Now
    </span>
  );
}

// The API's messages, made readable: without the validator's "Value error, "
// prefix, and naming the field when the message does not say which it is.
// Mistakes the person can fix themselves (422, 409) need no support reference.
const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  starts_on: "Starts on",
  ends_on: "Ends on",
};

function describeError(status: number, error: ApiErrorBody): string {
  if (status === 409) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details
      .map((detail) => {
        const message = detail.message.replace(/^Value error, /, "");
        const label = detail.field.startsWith("terms.") ? "Term dates" : FIELD_LABELS[detail.field];
        return label ? `${label}: ${message}` : message;
      })
      .join(" ");
  }
  return withReference(error);
}

// A form in a bordered panel whose heading takes focus when it opens.
function Panel({ title, children }: { title: string; children: ReactNode }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <section
      aria-labelledby="year-form-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2
        id="year-form-heading"
        ref={headingRef}
        tabIndex={-1}
        className="mb-4 text-xl font-semibold focus:outline-none"
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function DateInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        {label}
      </label>
      <input
        id={id}
        type="date"
        min={EARLIEST_DATE}
        max={LATEST_DATE}
        className={inputClass}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function FormButtons({ pending, label, onCancel }: { pending: boolean; label: string; onCancel: () => void }) {
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <button type="submit" className={inlineButtonClass} disabled={pending}>
        {pending ? "Saving..." : label}
      </button>
      <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
        Cancel
      </button>
    </div>
  );
}

type Saving = { onSaved: (message: string) => void; onCancel: () => void };

// Sends one change to the API and reports the result. Returns the error
// message to show, or null once saved.
async function send(
  path: string,
  method: "POST" | "PATCH" | "PUT",
  body: unknown,
): Promise<{ year: AcademicYear } | { error: string } | null> {
  const response = await api<{ academic_year: AcademicYear }>(path, { method, body });
  if (response.status === 401) {
    goToLogin(PATH);
    return null;
  }
  return response.ok ? { year: response.data.academic_year } : { error: describeError(response.status, response.error) };
}

type TermDates = { starts_on: string; ends_on: string };

function AddYearForm({ onSaved, onCancel }: Saving) {
  const [name, setName] = useState("");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [terms, setTerms] = useState<TermDates[]>(TERM_NUMBERS.map(() => ({ starts_on: "", ends_on: "" })));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function setTerm(index: number, field: keyof TermDates, value: string) {
    setTerms((current) => current.map((term, i) => (i === index ? { ...term, [field]: value } : term)));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim() || !startsOn || !endsOn) {
      setError("Enter the name and both dates of the school year.");
      return;
    }
    const half = terms.findIndex((term) => !term.starts_on !== !term.ends_on);
    if (half >= 0) {
      setError(`Enter both dates of Term ${TERM_NUMBERS[half]}, or leave both empty.`);
      return;
    }
    const body = {
      name: name.trim(),
      starts_on: startsOn,
      ends_on: endsOn,
      terms: terms
        .map((term, i) => ({ number: TERM_NUMBERS[i], ...term }))
        .filter((term) => term.starts_on),
    };
    setPending(true);
    const result = await send(YEARS, "POST", body);
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onSaved(`Added the school year ${result.year.name}.`);
    }
  }

  return (
    <Panel title="Add a school year">
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="year-name" className={labelClass}>
              Name
            </label>
            <input
              id="year-name"
              autoComplete="off"
              required
              maxLength={MAX_YEAR_NAME}
              placeholder="2027"
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DateInput id="year-starts" label="Starts on" value={startsOn} onChange={setStartsOn} />
          <DateInput id="year-ends" label="Ends on" value={endsOn} onChange={setEndsOn} />
        </div>
        <fieldset className="mt-6">
          <legend className="mb-2 font-medium">
            Terms <span className="font-normal text-zinc-600 dark:text-zinc-400">(optional, can be added later)</span>
          </legend>
          <div className="grid gap-4 sm:grid-cols-3">
            {TERM_NUMBERS.map((number, i) => (
              <div key={number} className="grid gap-2">
                <DateInput
                  id={`term-${number}-starts`}
                  label={`Term ${number} starts on`}
                  value={terms[i].starts_on}
                  onChange={(value) => setTerm(i, "starts_on", value)}
                />
                <DateInput
                  id={`term-${number}-ends`}
                  label={`Term ${number} ends on`}
                  value={terms[i].ends_on}
                  onChange={(value) => setTerm(i, "ends_on", value)}
                />
              </div>
            ))}
          </div>
        </fieldset>
        <FormButtons pending={pending} label="Add school year" onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function EditYearForm({ year, onSaved, onCancel }: Saving & { year: AcademicYear }) {
  const [name, setName] = useState(year.name);
  const [startsOn, setStartsOn] = useState(year.starts_on);
  const [endsOn, setEndsOn] = useState(year.ends_on);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim() || !startsOn || !endsOn) {
      setError("Enter the name and both dates of the school year.");
      return;
    }
    // Send only what changed.
    const body: Record<string, string> = {};
    if (name.trim() !== year.name) {
      body.name = name.trim();
    }
    if (startsOn !== year.starts_on) {
      body.starts_on = startsOn;
    }
    if (endsOn !== year.ends_on) {
      body.ends_on = endsOn;
    }
    if (Object.keys(body).length === 0) {
      onCancel();
      return;
    }
    setPending(true);
    const result = await send(`${YEARS}/${year.id}`, "PATCH", body);
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onSaved(`Saved changes to the school year ${result.year.name}.`);
    }
  }

  return (
    <Panel title={`Edit the school year ${year.name}`}>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="year-name" className={labelClass}>
              Name
            </label>
            <input
              id="year-name"
              autoComplete="off"
              required
              maxLength={MAX_YEAR_NAME}
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DateInput id="year-starts" label="Starts on" value={startsOn} onChange={setStartsOn} />
          <DateInput id="year-ends" label="Ends on" value={endsOn} onChange={setEndsOn} />
        </div>
        <FormButtons pending={pending} label="Save changes" onCancel={onCancel} />
      </form>
    </Panel>
  );
}

function TermForm({ year, number, onSaved, onCancel }: Saving & { year: AcademicYear; number: number }) {
  const term = year.terms.find((t) => t.number === number);
  const [startsOn, setStartsOn] = useState(term?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(term?.ends_on ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!startsOn || !endsOn) {
      setError(`Enter both dates of Term ${number}.`);
      return;
    }
    setPending(true);
    const result = await send(`${YEARS}/${year.id}/terms/${number}`, "PUT", {
      starts_on: startsOn,
      ends_on: endsOn,
    });
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onSaved(`Saved the dates of Term ${number} of ${result.year.name}.`);
    }
  }

  return (
    <Panel title={`Term ${number} of ${year.name}`}>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        The school year runs from {formatCalendarDate(year.starts_on)} to {formatCalendarDate(year.ends_on)}.
      </p>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <DateInput id="term-starts" label="Starts on" value={startsOn} onChange={setStartsOn} />
          <DateInput id="term-ends" label="Ends on" value={endsOn} onChange={setEndsOn} />
        </div>
        <FormButtons pending={pending} label="Save term" onCancel={onCancel} />
      </form>
    </Panel>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
