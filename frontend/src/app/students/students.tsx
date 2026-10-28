"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

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
  MAX_ADMISSION_NUMBER,
  MAX_NAME,
  MAX_SEARCH,
  PER_PAGE,
  formatBirthDate,
  oldestBirthDateIso,
  todayIso,
  type Student,
  type StudentFields,
  type StudentPage,
} from "@/lib/students";

const PATH = "/students";

export function Students() {
  return <AppShell path={PATH}>{(me) => <StudentsContent me={me} />}</AppShell>;
}

function StudentsContent({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Students</h1>
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
  if (!me.permissions.includes("students.read")) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Students</h1>
        <p>You do not have access to this page in {school.name}.</p>
      </section>
    );
  }
  // Keyed by school, so switching school starts this page afresh.
  return (
    <StudentsList
      key={school.id}
      schoolName={school.name}
      canManage={me.permissions.includes("students.manage")}
    />
  );
}

// The search text stays in this page's memory and goes to the API only. It
// is never put in the page's own address, so children's names do not end up
// in the browser history. `version` changes to reload after a change.
type Query = { q: string; page: number; version: number };

// The add or edit panel, when open.
type Editing = { mode: "add" } | { mode: "edit"; student: Student } | null;

function StudentsList({ schoolName, canManage }: { schoolName: string; canManage: boolean }) {
  const [query, setQuery] = useState<Query>({ q: "", page: 1, version: 0 });
  const [searchText, setSearchText] = useState("");
  const [result, setResult] = useState<StudentPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Editing>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(query.page), per_page: String(PER_PAGE) });
    if (query.q) {
      params.set("q", query.q);
    }
    api<StudentPage>(`/school/students?${params}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(PATH);
        return;
      }
      setLoading(false);
      if (response.ok) {
        setResult(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [query]);

  function reload() {
    setLoading(true);
    setQuery((current) => ({ ...current, version: current.version + 1 }));
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    setQuery((current) => ({ q: searchText.trim(), page: 1, version: current.version }));
  }

  function clearSearch() {
    setSearchText("");
    setError(null);
    setLoading(true);
    setQuery((current) => ({ q: "", page: 1, version: current.version }));
  }

  function goToPage(page: number) {
    setLoading(true);
    setQuery((current) => ({ ...current, page }));
  }

  function openPanel(next: Editing) {
    setError(null);
    setNotice(null);
    setConfirmingId(null);
    setEditing(next);
  }

  function saved(message: string) {
    setEditing(null);
    setNotice(message);
    reload();
  }

  async function deactivate(student: Student) {
    setBusy(true);
    const response = await api<{ student: Student }>(
      `/school/students/${student.id}/deactivate`,
      { method: "POST" },
    );
    setBusy(false);
    setConfirmingId(null);
    if (response.status === 401) {
      goToLogin(PATH);
      return;
    }
    if (response.ok) {
      setNotice(`${student.full_name} (${student.admission_number}) is now inactive.`);
    } else {
      setError(withReference(response.error));
    }
    reload();
  }

  const lastPage = result ? Math.max(1, Math.ceil(result.total / result.per_page)) : 1;
  const first = result && result.total > 0 ? (result.page - 1) * result.per_page + 1 : 0;
  const last = result && first > 0 ? first + result.students.length - 1 : 0;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">Students</h1>
          <p className="text-zinc-600 dark:text-zinc-400">{schoolName}</p>
        </div>
        {canManage && !editing && (
          <button type="button" className={inlineButtonClass} onClick={() => openPanel({ mode: "add" })}>
            Add a student
          </button>
        )}
      </div>

      {editing && (
        <StudentForm
          key={editing.mode === "edit" ? editing.student.id : "add"}
          student={editing.mode === "edit" ? editing.student : null}
          onSaved={saved}
          onCancel={() => setEditing(null)}
        />
      )}

      <form onSubmit={search} role="search" className="mb-6 flex max-w-xl flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <label htmlFor="student-search" className={labelClass}>
            Search by name or admission number
          </label>
          <input
            id="student-search"
            type="search"
            autoComplete="off"
            maxLength={MAX_SEARCH}
            className={inputClass}
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
        </div>
        <button type="submit" className={inlineButtonClass}>
          Search
        </button>
        {query.q && (
          <button type="button" className={secondaryButtonClass} onClick={clearSearch}>
            Clear
          </button>
        )}
      </form>

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      <p role="status" className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">
        {loading
          ? "Loading..."
          : result && result.total > 0
            ? `Showing ${first} to ${last} of ${result.total} student${result.total === 1 ? "" : "s"}${query.q ? ` matching "${query.q}"` : ""}.`
            : result
              ? query.q
                ? `No students match "${query.q}".`
                : "No students yet."
              : ""}
      </p>

      {result && result.students.length > 0 && (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
            <caption className="sr-only">Students in {schoolName}</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Admission no.</th>
                <th scope="col" className={thClass}>Name</th>
                <th scope="col" className={thClass}>Date of birth</th>
                <th scope="col" className={thClass}>Status</th>
                {canManage && (
                  <th scope="col" className={thClass}>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {result.students.map((student) => (
                <tr key={student.id}>
                  <td className={tdClass}>{student.admission_number}</td>
                  <td className={tdClass}>
                    <Link href={`/students/${student.id}`} className="underline">
                      {student.full_name}
                    </Link>
                  </td>
                  <td className={tdClass}>{formatBirthDate(student.date_of_birth)}</td>
                  <td className={tdClass}>{student.is_active ? "Active" : "Inactive"}</td>
                  {canManage && (
                    <td className={tdClass}>
                      {confirmingId === student.id ? (
                        <ConfirmDeactivate
                          student={student}
                          busy={busy}
                          onConfirm={() => deactivate(student)}
                          onCancel={() => setConfirmingId(null)}
                        />
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            className={`${secondaryButtonClass} py-1`}
                            aria-label={`Edit ${student.full_name} (${student.admission_number})`}
                            onClick={() => openPanel({ mode: "edit", student })}
                            disabled={busy}
                          >
                            Edit
                          </button>
                          {student.is_active && (
                            <button
                              type="button"
                              className={`${secondaryButtonClass} py-1`}
                              aria-label={`Deactivate ${student.full_name} (${student.admission_number})`}
                              onClick={() => {
                                setError(null);
                                setNotice(null);
                                setConfirmingId(student.id);
                              }}
                              disabled={busy}
                            >
                              Deactivate
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && lastPage > 1 && (
        <nav aria-label="Pages of students" className="mt-4 flex items-center gap-3">
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={() => goToPage(query.page - 1)}
            disabled={loading || query.page <= 1}
          >
            Previous
          </button>
          <span className="text-sm">
            Page {query.page} of {lastPage}
          </span>
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={() => goToPage(query.page + 1)}
            disabled={loading || query.page >= lastPage}
          >
            Next
          </button>
        </nav>
      )}
    </>
  );
}

const FIELD_LABELS: Record<string, string> = {
  admission_number: "Admission number",
  full_name: "Full name",
  date_of_birth: "Date of birth",
};

// The API's field messages, made readable: without the validator's
// "Value error, " prefix, and naming the field unless the message already does.
function describeError(error: ApiErrorBody): string {
  if (error.details && error.details.length > 0) {
    return error.details
      .map((detail) => {
        const message = detail.message.replace(/^Value error, /, "");
        const label = FIELD_LABELS[detail.field];
        return !label || message.startsWith(label) ? message : `${label}: ${message}`;
      })
      .join(" ");
  }
  return withReference(error);
}

function StudentForm({
  student,
  onSaved,
  onCancel,
}: {
  student: Student | null;
  onSaved: (message: string) => void;
  onCancel: () => void;
}) {
  const initial: StudentFields = {
    admission_number: student?.admission_number ?? "",
    full_name: student?.full_name ?? "",
    date_of_birth: student?.date_of_birth ?? "",
  };
  const [fields, setFields] = useState<StudentFields>(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const title = student
    ? `Edit ${student.full_name} (${student.admission_number})`
    : "Add a student";

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  function update(name: keyof StudentFields, value: string) {
    setFields((current) => ({ ...current, [name]: value }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const admissionNumber = fields.admission_number.trim();
    const fullName = fields.full_name.trim();
    if (!admissionNumber || !fullName) {
      setError("Enter the admission number and full name.");
      return;
    }
    const values = {
      admission_number: admissionNumber,
      full_name: fullName,
      date_of_birth: fields.date_of_birth || null,
    };

    let body: Record<string, string | null> = values;
    if (student) {
      // Send only what changed.
      body = {};
      if (values.admission_number !== student.admission_number) {
        body.admission_number = values.admission_number;
      }
      if (values.full_name !== student.full_name) {
        body.full_name = values.full_name;
      }
      if (values.date_of_birth !== student.date_of_birth) {
        body.date_of_birth = values.date_of_birth;
      }
      if (Object.keys(body).length === 0) {
        onCancel();
        return;
      }
    }

    setPending(true);
    const response = await api<{ student: Student }>(
      student ? `/school/students/${student.id}` : "/school/students",
      { method: student ? "PATCH" : "POST", body },
    );
    setPending(false);
    if (response.status === 401) {
      goToLogin(PATH);
      return;
    }
    if (response.ok) {
      const saved = response.data.student;
      onSaved(
        student
          ? `Saved changes to ${saved.full_name} (${saved.admission_number}).`
          : `Added ${saved.full_name} (${saved.admission_number}).`,
      );
    } else {
      setError(describeError(response.error));
    }
  }

  return (
    <section
      aria-labelledby="student-form-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2
        id="student-form-heading"
        ref={headingRef}
        tabIndex={-1}
        className="mb-4 text-xl font-semibold focus:outline-none"
      >
        {title}
      </h2>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="admission-number" className={labelClass}>
              Admission number
            </label>
            <input
              id="admission-number"
              autoComplete="off"
              required
              maxLength={MAX_ADMISSION_NUMBER}
              className={inputClass}
              value={fields.admission_number}
              onChange={(event) => update("admission_number", event.target.value)}
            />
          </div>
          <div>
            <label htmlFor="student-name" className={labelClass}>
              Full name
            </label>
            <input
              id="student-name"
              autoComplete="off"
              required
              maxLength={MAX_NAME}
              className={inputClass}
              value={fields.full_name}
              onChange={(event) => update("full_name", event.target.value)}
            />
          </div>
          <div>
            <label htmlFor="date-of-birth" className={labelClass}>
              Date of birth <span className="font-normal">(optional)</span>
            </label>
            <input
              id="date-of-birth"
              type="date"
              min={oldestBirthDateIso()}
              max={todayIso()}
              className={inputClass}
              value={fields.date_of_birth}
              onChange={(event) => update("date_of_birth", event.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Saving..." : student ? "Save changes" : "Add student"}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

// "Deactivate" turns into a question with "Yes" and "Cancel" in the same
// place, instead of a browser pop-up. Focus moves to "Yes".
function ConfirmDeactivate({
  student,
  busy,
  onConfirm,
  onCancel,
}: {
  student: Student;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const yesRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    yesRef.current?.focus();
  }, []);
  return (
    <div className="flex flex-col gap-2">
      <span>Deactivate {student.full_name}? This cannot be undone here yet.</span>
      <div className="flex gap-2">
        <button
          ref={yesRef}
          type="button"
          className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
          onClick={onConfirm}
          disabled={busy}
        >
          Yes, deactivate
        </button>
        <button type="button" className={`${secondaryButtonClass} py-1`} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
