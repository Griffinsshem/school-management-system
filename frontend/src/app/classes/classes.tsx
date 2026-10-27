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
import type { AcademicYearList } from "@/lib/academic-years";
import {
  MAX_STREAM,
  defaultYearId,
  type ClassList,
  type Grade,
  type SchoolClass,
} from "@/lib/classes";
import type { Member } from "@/lib/people";

const PATH = "/classes";
const CLASSES = "/school/classes";

export function Classes() {
  return <AppShell path={PATH}>{(me) => <ClassesContent me={me} />}</AppShell>;
}

function ClassesContent({ me }: { me: Me }) {
  const school = me.active_school;
  const seesAll = me.permissions.includes("classes.read");
  const seesOwn = me.permissions.includes("classes.read_own");
  if (!school) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Classes</h1>
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
  if (!seesAll && !seesOwn) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Classes</h1>
        <p>You do not have access to this page in {school.name}.</p>
      </section>
    );
  }
  // Keyed by school, so switching school starts this page afresh.
  return (
    <ClassesPage
      key={school.id}
      schoolName={school.name}
      onlyMine={!seesAll}
      canManage={me.permissions.includes("classes.manage")}
    />
  );
}

// The API's messages, made readable (see the students page).
function describeError(status: number, error: ApiErrorBody): string {
  if (status === 409) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details
      .map((detail) => {
        const message = detail.message.replace(/^Value error, /, "");
        return detail.field === "stream" ? `Stream: ${message}` : message;
      })
      .join(" ");
  }
  return withReference(error);
}

function ClassesPage({
  schoolName,
  onlyMine,
  canManage,
}: {
  schoolName: string;
  onlyMine: boolean;
  canManage: boolean;
}) {
  const [years, setYears] = useState<AcademicYearList | null>(null);
  const [yearId, setYearId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = onlyMine ? "My classes" : "Classes";

  useEffect(() => {
    let cancelled = false;
    api<AcademicYearList>("/school/academic-years").then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(PATH);
      } else if (response.ok) {
        setYears(response.data);
        setYearId(defaultYearId(response.data));
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="text-zinc-600 dark:text-zinc-400">{schoolName}</p>
        </div>
        {years && yearId && (
          <div>
            <label htmlFor="year" className={labelClass}>
              School year
            </label>
            <select
              id="year"
              className={inputClass}
              value={yearId}
              onChange={(event) => setYearId(event.target.value)}
            >
              {years.academic_years.map((year) => (
                <option key={year.id} value={year.id}>
                  {year.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <ErrorMessage message={error} />

      {!years ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : !yearId ? (
        <p>
          No school years yet.{" "}
          {canManage && (
            <>
              Add one on the{" "}
              <Link href="/school-year" className="underline">
                School year
              </Link>{" "}
              page first.
            </>
          )}
        </p>
      ) : (
        <YearClasses key={yearId} yearId={yearId} onlyMine={onlyMine} canManage={canManage} />
      )}
    </>
  );
}

type Editing = { mode: "add" } | { mode: "edit"; classId: string } | null;

function YearClasses({
  yearId,
  onlyMine,
  canManage,
}: {
  yearId: string;
  onlyMine: boolean;
  canManage: boolean;
}) {
  const [list, setList] = useState<ClassList | null>(null);
  const [version, setVersion] = useState(0);
  const [teachers, setTeachers] = useState<Member[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ academic_year_id: yearId });
    api<ClassList>(`${CLASSES}?${params}`).then((response) => {
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
  }, [yearId, version]);

  // The school's active teachers, for choosing class teachers.
  useEffect(() => {
    if (!canManage) {
      return;
    }
    let cancelled = false;
    api<{ members: Member[] }>("/school/members").then((response) => {
      if (!cancelled && response.ok) {
        setTeachers(response.data.members.filter((m) => m.role === "teacher" && m.is_active));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [canManage]);

  function open(next: Editing) {
    setError(null);
    setNotice(null);
    setEditing(next);
  }

  // After a change: show what happened and load the list again.
  function changed(message: string, keepOpen: boolean) {
    setNotice(message);
    if (!keepOpen) {
      setEditing(null);
    }
    setVersion((current) => current + 1);
  }

  const editingClass =
    editing?.mode === "edit" ? list?.classes.find((c) => c.id === editing.classId) : undefined;

  if (!list) {
    return error ? <ErrorMessage message={error} /> : <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>;
  }

  return (
    <>
      {canManage && !editing && (
        <div className="mb-6">
          <button type="button" className={inlineButtonClass} onClick={() => open({ mode: "add" })}>
            Add a class
          </button>
        </div>
      )}

      {editing?.mode === "add" && (
        <AddClassForm
          yearId={yearId}
          yearName={list.academic_year.name}
          grades={list.grades}
          onSaved={(name) => changed(`Added ${name}.`, false)}
          onCancel={() => setEditing(null)}
        />
      )}
      {editingClass && (
        <EditClassPanel
          key={editingClass.id}
          schoolClass={editingClass}
          grades={list.grades}
          teachers={teachers}
          onChanged={changed}
          onClose={() => setEditing(null)}
        />
      )}

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {list.classes.length === 0 ? (
        <p>
          {onlyMine
            ? `You are not a class teacher of any class in ${list.academic_year.name}.`
            : `No classes in ${list.academic_year.name} yet.`}
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Classes in {list.academic_year.name}</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Class</th>
                <th scope="col" className={thClass}>Class teachers</th>
                {canManage && (
                  <th scope="col" className={thClass}>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {list.classes.map((schoolClass) => (
                <tr key={schoolClass.id}>
                  <th scope="row" className={`${tdClass} font-medium`}>
                    {schoolClass.name}
                  </th>
                  <td className={tdClass}>
                    <TeacherNames schoolClass={schoolClass} />
                  </td>
                  {canManage && (
                    <td className={tdClass}>
                      <button
                        type="button"
                        className={`${secondaryButtonClass} py-1`}
                        aria-label={`Edit ${schoolClass.name}`}
                        onClick={() => open({ mode: "edit", classId: schoolClass.id })}
                        disabled={editing !== null}
                      >
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function TeacherNames({ schoolClass }: { schoolClass: SchoolClass }) {
  if (schoolClass.teachers.length === 0) {
    return <span className="text-zinc-600 dark:text-zinc-400">None yet</span>;
  }
  return (
    <ul>
      {schoolClass.teachers.map((teacher) => (
        <li key={teacher.membership_id}>
          {teacher.full_name}
          {!teacher.is_active && <FormerTeacher />}
        </li>
      ))}
    </ul>
  );
}

function FormerTeacher() {
  return <span className="text-zinc-600 dark:text-zinc-400"> (no longer a teacher here)</span>;
}

// A form in a bordered panel whose heading takes focus when it opens.
function Panel({ title, children }: { title: string; children: ReactNode }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <section
      aria-labelledby="class-panel-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2
        id="class-panel-heading"
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

function ClassFields({
  grades,
  grade,
  stream,
  onGrade,
  onStream,
}: {
  grades: Grade[];
  grade: string;
  stream: string;
  onGrade: (value: string) => void;
  onStream: (value: string) => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <label htmlFor="class-grade" className={labelClass}>
          Grade
        </label>
        <select
          id="class-grade"
          className={inputClass}
          value={grade}
          onChange={(event) => onGrade(event.target.value)}
        >
          {grade === "" && <option value="">Choose a grade</option>}
          {grades.map((option) => (
            <option key={option.code} value={option.code}>
              {option.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="class-stream" className={labelClass}>
          Stream <span className="font-normal">(optional, for example East)</span>
        </label>
        <input
          id="class-stream"
          autoComplete="off"
          maxLength={MAX_STREAM}
          className={inputClass}
          value={stream}
          onChange={(event) => onStream(event.target.value)}
        />
      </div>
    </div>
  );
}

async function sendClass(
  path: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown,
): Promise<{ schoolClass: SchoolClass } | { error: string } | null> {
  const response = await api<{ class: SchoolClass }>(path, { method, body });
  if (response.status === 401) {
    goToLogin(PATH);
    return null;
  }
  return response.ok
    ? { schoolClass: response.data.class }
    : { error: describeError(response.status, response.error) };
}

function AddClassForm({
  yearId,
  yearName,
  grades,
  onSaved,
  onCancel,
}: {
  yearId: string;
  yearName: string;
  grades: Grade[];
  onSaved: (name: string) => void;
  onCancel: () => void;
}) {
  const [grade, setGrade] = useState("");
  const [stream, setStream] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!grade) {
      setError("Choose a grade.");
      return;
    }
    setPending(true);
    const result = await sendClass(CLASSES, "POST", {
      academic_year_id: yearId,
      grade,
      stream: stream.trim() || null,
    });
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onSaved(result.schoolClass.name);
    }
  }

  return (
    <Panel title={`Add a class to ${yearName}`}>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Only the grades that exist in {yearName} are offered.
      </p>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <ClassFields grades={grades} grade={grade} stream={stream} onGrade={setGrade} onStream={setStream} />
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Saving..." : "Add class"}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  );
}

function EditClassPanel({
  schoolClass,
  grades,
  teachers,
  onChanged,
  onClose,
}: {
  schoolClass: SchoolClass;
  grades: Grade[];
  teachers: Member[];
  onChanged: (message: string, keepOpen: boolean) => void;
  onClose: () => void;
}) {
  const [grade, setGrade] = useState(schoolClass.grade);
  const [stream, setStream] = useState(schoolClass.stream ?? "");
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const path = `${CLASSES}/${schoolClass.id}`;
  // A class keeps its grade even if the list of grades no longer offers it.
  const gradeOptions = grades.some((g) => g.code === schoolClass.grade)
    ? grades
    : [{ code: schoolClass.grade, name: schoolClass.grade_name }, ...grades];
  const assigned = new Set(schoolClass.teachers.map((t) => t.membership_id));
  const available = teachers
    .filter((t) => !assigned.has(t.id))
    .sort((a, b) => a.user.full_name.localeCompare(b.user.full_name));

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    // Send only what changed.
    const body: Record<string, string | null> = {};
    if (grade !== schoolClass.grade) {
      body.grade = grade;
    }
    const newStream = stream.trim() || null;
    if (newStream !== schoolClass.stream) {
      body.stream = newStream;
    }
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setPending(true);
    const result = await sendClass(path, "PATCH", body);
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onChanged(`Saved ${result.schoolClass.name}.`, false);
    }
  }

  async function addTeacher(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const teacher = teachers.find((t) => t.id === chosen);
    if (!teacher) {
      setError("Choose a teacher to add.");
      return;
    }
    setPending(true);
    const result = await sendClass(`${path}/teachers`, "POST", { membership_id: teacher.id });
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      setChosen("");
      onChanged(`${teacher.user.full_name} is now a class teacher of ${schoolClass.name}.`, true);
    }
  }

  async function removeTeacher(membershipId: string, name: string) {
    setError(null);
    setPending(true);
    const result = await sendClass(`${path}/teachers/${membershipId}`, "DELETE");
    setPending(false);
    if (result && "error" in result) {
      setError(result.error);
    } else if (result) {
      onChanged(`${name} is no longer a class teacher of ${schoolClass.name}.`, true);
    }
  }

  return (
    <Panel title={`Edit ${schoolClass.name}`}>
      <ErrorMessage message={error} />
      <form onSubmit={save} noValidate>
        <ClassFields grades={gradeOptions} grade={grade} stream={stream} onGrade={setGrade} onStream={setStream} />
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            Save changes
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={pending}>
            Close
          </button>
        </div>
      </form>

      <h3 className="mt-6 mb-2 font-semibold">Class teachers</h3>
      {schoolClass.teachers.length === 0 ? (
        <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">None yet.</p>
      ) : (
        <ul className="mb-3 grid gap-2">
          {schoolClass.teachers.map((teacher) => (
            <li key={teacher.membership_id} className="flex flex-wrap items-center gap-2">
              <span>
                {teacher.full_name}
                {!teacher.is_active && <FormerTeacher />}
              </span>
              <button
                type="button"
                className={`${secondaryButtonClass} py-1`}
                aria-label={`Remove ${teacher.full_name} from ${schoolClass.name}`}
                onClick={() => removeTeacher(teacher.membership_id, teacher.full_name)}
                disabled={pending}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {available.length > 0 ? (
        <form onSubmit={addTeacher} noValidate className="flex max-w-md flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <label htmlFor="class-teacher" className={labelClass}>
              Add a class teacher
            </label>
            <select
              id="class-teacher"
              className={inputClass}
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
            >
              <option value="">Choose a teacher</option>
              {available.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {teacher.user.full_name}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            Add
          </button>
        </form>
      ) : (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {teachers.length === 0
            ? "This school has no active teachers yet. Invite them on the People page."
            : "Every active teacher is already a class teacher of this class."}
        </p>
      )}
    </Panel>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
