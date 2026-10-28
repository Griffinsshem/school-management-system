"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
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
import type { ClassList as YearClasses } from "@/lib/classes";
import { MAX_ENROL_AT_ONCE, type ClassList, type ClassStudent } from "@/lib/enrolments";
import { MAX_SEARCH, type StudentPage } from "@/lib/students";

// The menu marks "Classes" as the current page.
const MENU_PATH = "/classes";

export function ClassStudents() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path={MENU_PATH}>{(me) => <Content me={me} classId={id} />}</AppShell>;
}

function Content({ me, classId }: { me: Me; classId: string }) {
  const school = me.active_school;
  const canRead =
    me.permissions.includes("classes.read") || me.permissions.includes("classes.read_own");
  if (!school || !canRead) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Class list</h1>
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
  // Keyed by school, so switching school starts this page afresh.
  return (
    <Students
      key={school.id}
      classId={classId}
      canManage={me.permissions.includes("enrolments.manage")}
    />
  );
}

// The API's messages, made readable (see the students page).
function describeError(status: number, error: ApiErrorBody): string {
  if (status === 409 || status === 404) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details.map((d) => d.message.replace(/^Value error, /, "")).join(" ");
  }
  return withReference(error);
}

function Students({ classId, canManage }: { classId: string; canManage: boolean }) {
  const path = `/school/classes/${classId}/students`;
  const [list, setList] = useState<ClassList | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<ClassList>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(`/classes/${classId}`);
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
  }, [path, classId, version]);

  // After a change: show what happened and load the list again.
  function changed(message: string) {
    setError(null);
    setNotice(message);
    setVersion((current) => current + 1);
  }

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Class not found</h1>
        <p>
          This class does not exist, or it is not one of yours.{" "}
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

  const count = list.students.length;
  return (
    <>
      <p className="mb-2">
        <Link href="/classes" className="text-sm underline">
          Back to the classes
        </Link>
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">{list.class.name}</h1>
          <p className="text-zinc-600 dark:text-zinc-400">
            {count} student{count === 1 ? "" : "s"}
          </p>
        </div>
        {canManage && !adding && (
          <button
            type="button"
            className={inlineButtonClass}
            onClick={() => {
              setError(null);
              setNotice(null);
              setAdding(true);
            }}
          >
            Add students
          </button>
        )}
      </div>

      {adding && (
        <AddStudents
          classPath={path}
          className={list.class.name}
          yearId={list.class.academic_year_id}
          onEnrolled={(message) => changed(message)}
          onClose={() => setAdding(false)}
        />
      )}

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {count === 0 ? (
        <p>No students in {list.class.name} yet.</p>
      ) : (
        <StudentTable
          list={list}
          canManage={canManage}
          onChanged={changed}
          onError={setError}
        />
      )}
    </>
  );
}

function StudentTable({
  list,
  canManage,
  onChanged,
  onError,
}: {
  list: ClassList;
  canManage: boolean;
  onChanged: (message: string) => void;
  onError: (message: string | null) => void;
}) {
  const [classes, setClasses] = useState<YearClasses["classes"]>([]);
  const showStatus = list.students.some((s) => s.is_active !== undefined);

  // The other classes of the same year, for moving students.
  useEffect(() => {
    if (!canManage) {
      return;
    }
    let cancelled = false;
    const params = new URLSearchParams({ academic_year_id: list.class.academic_year_id });
    api<YearClasses>(`/school/classes?${params}`).then((response) => {
      if (!cancelled && response.ok) {
        setClasses(response.data.classes.filter((c) => c.id !== list.class.id));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [canManage, list.class.academic_year_id, list.class.id]);

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Students in {list.class.name}</caption>
        <thead>
          <tr>
            <th scope="col" className={thClass}>Admission no.</th>
            <th scope="col" className={thClass}>Name</th>
            {showStatus && <th scope="col" className={thClass}>Status</th>}
            {canManage && (
              <th scope="col" className={thClass}>
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {list.students.map((student) => (
            <tr key={student.id}>
              <td className={tdClass}>{student.admission_number}</td>
              <td className={tdClass}>{student.full_name}</td>
              {showStatus && (
                <td className={tdClass}>{student.is_active ? "Active" : "Inactive"}</td>
              )}
              {canManage && (
                <td className={tdClass}>
                  <StudentActions
                    student={student}
                    list={list}
                    classes={classes}
                    onChanged={onChanged}
                    onError={onError}
                  />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// "Move" and "Remove" open in place, each with its own confirmation.
function StudentActions({
  student,
  list,
  classes,
  onChanged,
  onError,
}: {
  student: ClassStudent;
  list: ClassList;
  classes: YearClasses["classes"];
  onChanged: (message: string) => void;
  onError: (message: string | null) => void;
}) {
  const [mode, setMode] = useState<"idle" | "move" | "remove">("idle");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const selectRef = useRef<HTMLSelectElement>(null);
  const yesRef = useRef<HTMLButtonElement>(null);
  const label = `${student.full_name} (${student.admission_number})`;
  const studentPath = `/school/classes/${list.class.id}/students/${student.id}`;

  useEffect(() => {
    // Focus moves into the question that just opened.
    if (mode === "move") {
      selectRef.current?.focus();
    } else if (mode === "remove") {
      yesRef.current?.focus();
    }
  }, [mode]);

  async function send(method: "PATCH" | "DELETE", body: unknown, message: string) {
    onError(null);
    setBusy(true);
    const response = await api(studentPath, { method, body });
    setBusy(false);
    if (response.status === 401) {
      goToLogin(`/classes/${list.class.id}`);
    } else if (response.ok) {
      setMode("idle");
      onChanged(message);
    } else {
      onError(describeError(response.status, response.error));
    }
  }

  function move(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const to = classes.find((c) => c.id === target);
    if (!to) {
      onError("Choose the class to move to.");
      return;
    }
    send("PATCH", { class_id: to.id }, `Moved ${label} to ${to.name}.`);
  }

  if (mode === "move") {
    return (
      <form onSubmit={move} className="flex flex-wrap items-end gap-2" noValidate>
        <div>
          <label htmlFor={`move-${student.id}`} className={labelClass}>
            Move {student.full_name} to
          </label>
          <select
            id={`move-${student.id}`}
            ref={selectRef}
            className={inputClass}
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">Choose a class</option>
            {classes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className={`${inlineButtonClass} py-1`} disabled={busy}>
          Move
        </button>
        <button type="button" className={`${secondaryButtonClass} py-1`} onClick={() => setMode("idle")} disabled={busy}>
          Cancel
        </button>
      </form>
    );
  }
  if (mode === "remove") {
    return (
      <div className="flex flex-col gap-2">
        <span>Remove {student.full_name} from {list.class.name}?</span>
        <div className="flex gap-2">
          <button
            ref={yesRef}
            type="button"
            className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
            onClick={() => send("DELETE", undefined, `Removed ${label} from ${list.class.name}.`)}
            disabled={busy}
          >
            Yes, remove
          </button>
          <button type="button" className={`${secondaryButtonClass} py-1`} onClick={() => setMode("idle")} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {classes.length > 0 && (
        <button
          type="button"
          className={`${secondaryButtonClass} py-1`}
          aria-label={`Move ${label} to another class`}
          onClick={() => setMode("move")}
        >
          Move
        </button>
      )}
      <button
        type="button"
        className={`${secondaryButtonClass} py-1`}
        aria-label={`Remove ${label} from ${list.class.name}`}
        onClick={() => setMode("remove")}
      >
        Remove
      </button>
    </div>
  );
}

// Students with no class this year, searched by name or admission number
// and ticked for enrolling. The search text never goes into the address.
function AddStudents({
  classPath,
  className,
  yearId,
  onEnrolled,
  onClose,
}: {
  classPath: string;
  className: string;
  yearId: string;
  onEnrolled: (message: string) => void;
  onClose: () => void;
}) {
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState({ q: "", version: 0 });
  const [found, setFound] = useState<StudentPage | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ not_enrolled_in: yearId, per_page: "50" });
    if (query.q) {
      params.set("q", query.q);
    }
    api<StudentPage>(`/school/students?${params}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.ok) {
        setFound(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [yearId, query]);

  function toggle(id: string) {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery((current) => ({ q: searchText.trim(), version: current.version + 1 }));
  }

  async function enrol() {
    setError(null);
    if (chosen.size === 0) {
      setError("Tick the students to add.");
      return;
    }
    if (chosen.size > MAX_ENROL_AT_ONCE) {
      setError(`Add at most ${MAX_ENROL_AT_ONCE} students at a time.`);
      return;
    }
    setPending(true);
    const response = await api<ClassList>(classPath, {
      method: "POST",
      body: { student_ids: [...chosen] },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin("/classes");
    } else if (response.ok) {
      const n = chosen.size;
      setChosen(new Set());
      setQuery((current) => ({ ...current, version: current.version + 1 }));
      onEnrolled(`Added ${n} student${n === 1 ? "" : "s"} to ${className}.`);
    } else {
      setError(describeError(response.status, response.error));
    }
  }

  const n = chosen.size;
  return (
    <section
      aria-labelledby="add-students-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2 id="add-students-heading" ref={headingRef} tabIndex={-1} className="mb-1 text-xl font-semibold focus:outline-none">
        Add students to {className}
      </h2>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Only active students without a class this school year are listed.
      </p>
      <form onSubmit={search} role="search" className="mb-4 flex max-w-xl flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <label htmlFor="enrol-search" className={labelClass}>
            Search by name or admission number
          </label>
          <input
            id="enrol-search"
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
      </form>

      <ErrorMessage message={error} />

      {!found ? (
        <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : found.students.length === 0 ? (
        <p className="mb-4">
          {query.q ? `No students without a class match "${query.q}".` : "Every active student has a class this year."}
        </p>
      ) : (
        <fieldset className="mb-4">
          <legend className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">
            {found.total > found.students.length
              ? `Showing ${found.students.length} of ${found.total}. Search to narrow the list.`
              : `${found.total} student${found.total === 1 ? "" : "s"} without a class.`}
          </legend>
          <ul className="grid gap-1 sm:grid-cols-2">
            {found.students.map((student) => (
              <li key={student.id}>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={chosen.has(student.id)}
                    onChange={() => toggle(student.id)}
                  />
                  <span>
                    {student.full_name} <span className="text-zinc-600 dark:text-zinc-400">({student.admission_number})</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" className={inlineButtonClass} onClick={enrol} disabled={pending}>
          {pending ? "Adding..." : n > 0 ? `Add ${n} student${n === 1 ? "" : "s"}` : "Add students"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={pending}>
          Close
        </button>
      </div>
    </section>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
