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
  KCSE_CATEGORY_LABELS,
  MAX_SUBJECT_CODE,
  MAX_SUBJECT_NAME,
  canManageSubjects,
  canReadSubjects,
  type KcseCategory,
  type Subject,
} from "@/lib/subjects";

const PATH = "/subjects";
const SUBJECTS = "/school/subjects";

export function Subjects() {
  return <AppShell path={PATH}>{(me) => <Content me={me} />}</AppShell>;
}

function Content({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school || !canReadSubjects(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Subjects</h1>
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
  return <SubjectsPage key={school.id} schoolName={school.name} canManage={canManageSubjects(me)} />;
}

// The API's messages, made readable (see the students page).
function describeError(status: number, error: ApiErrorBody): string {
  if (status === 409 || status === 404) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details
      .map((detail) => {
        const message = detail.message.replace(/^Value error, /, "");
        if (detail.field === "name") {
          return `Name: ${message}`;
        }
        return detail.field === "code" ? `Code: ${message}` : message;
      })
      .join(" ");
  }
  return withReference(error);
}

type Editing = { mode: "add" } | { mode: "edit"; subjectId: string } | null;

function SubjectsPage({ schoolName, canManage }: { schoolName: string; canManage: boolean }) {
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ subjects: Subject[] }>(SUBJECTS).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(PATH);
      } else if (response.ok) {
        setSubjects(response.data.subjects);
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

  function changed(message: string) {
    setNotice(message);
    setEditing(null);
    setVersion((current) => current + 1);
  }

  const editingSubject =
    editing?.mode === "edit" ? subjects?.find((s) => s.id === editing.subjectId) : undefined;

  return (
    <>
      <div className="mb-6">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight">Subjects</h1>
        <p className="text-zinc-600 dark:text-zinc-400">{schoolName}</p>
      </div>
      <p className="mb-6 max-w-2xl">
        The subjects this school teaches. Choose which classes take each subject, and who teaches it, on
        each class&apos;s page. Subjects are never deleted: make one inactive when it is no longer
        offered, and it stays on the classes that already take it. Marks are graded on the scales on the{" "}
        <Link href="/grading" className="underline">
          Grading page
        </Link>
        .
      </p>

      {canManage && !editing && (
        <div className="mb-6">
          <button type="button" className={inlineButtonClass} onClick={() => open({ mode: "add" })}>
            Add a subject
          </button>
        </div>
      )}
      {editing?.mode === "add" && (
        <SubjectForm title="Add a subject" onSaved={changed} onCancel={() => setEditing(null)} />
      )}
      {editingSubject && (
        <SubjectForm
          key={editingSubject.id}
          title={`Edit ${editingSubject.name}`}
          subject={editingSubject}
          onSaved={changed}
          onCancel={() => setEditing(null)}
        />
      )}

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {!subjects ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : subjects.length === 0 ? (
        <p>No subjects yet.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Subjects</caption>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Subject</th>
                <th scope="col" className={thClass}>Code</th>
                <th scope="col" className={thClass}>Status</th>
                <th scope="col" className={thClass}>KCSE mean grade</th>
                {canManage && (
                  <th scope="col" className={thClass}>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {subjects.map((subject) => (
                <tr key={subject.id}>
                  <th scope="row" className={`${tdClass} font-medium`}>
                    {subject.name}
                  </th>
                  <td className={tdClass}>{subject.code ?? <span className="text-zinc-600 dark:text-zinc-400">None</span>}</td>
                  <td className={tdClass}>{subject.is_active ? "Active" : "Inactive"}</td>
                  <td className={tdClass}>{KCSE_CATEGORY_LABELS[subject.kcse_category]}</td>
                  {canManage && (
                    <td className={tdClass}>
                      <button
                        type="button"
                        className={`${secondaryButtonClass} py-1`}
                        aria-label={`Edit ${subject.name}`}
                        onClick={() => open({ mode: "edit", subjectId: subject.id })}
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

// A form in a bordered panel whose heading takes focus when it opens.
function Panel({ title, children }: { title: string; children: ReactNode }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <section
      aria-labelledby="subject-panel-heading"
      className="mb-8 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2
        id="subject-panel-heading"
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

function SubjectForm({
  title,
  subject,
  onSaved,
  onCancel,
}: {
  title: string;
  subject?: Subject;
  onSaved: (message: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(subject?.name ?? "");
  const [code, setCode] = useState(subject?.code ?? "");
  const [active, setActive] = useState(subject?.is_active ?? true);
  const [category, setCategory] = useState<KcseCategory>(subject?.kcse_category ?? "other");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Enter the subject's name.");
      return;
    }
    let body: Record<string, string | boolean | null>;
    if (subject) {
      // Send only what changed.
      body = {};
      if (name.trim() !== subject.name) {
        body.name = name;
      }
      if ((code.trim() || null) !== subject.code) {
        body.code = code.trim() || null;
      }
      if (active !== subject.is_active) {
        body.is_active = active;
      }
      if (category !== subject.kcse_category) {
        body.kcse_category = category;
      }
      if (Object.keys(body).length === 0) {
        onCancel();
        return;
      }
    } else {
      body = { name, code: code.trim() || null };
    }
    setPending(true);
    const response = await api<{ subject: Subject }>(subject ? `${SUBJECTS}/${subject.id}` : SUBJECTS, {
      method: subject ? "PATCH" : "POST",
      body,
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(PATH);
    } else if (response.ok) {
      onSaved(subject ? `Saved ${response.data.subject.name}.` : `Added ${response.data.subject.name}.`);
    } else {
      setError(describeError(response.status, response.error));
    }
  }

  return (
    <Panel title={title}>
      <form onSubmit={onSubmit} noValidate>
        <ErrorMessage message={error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="subject-name" className={labelClass}>
              Name <span className="font-normal">(for example Mathematics)</span>
            </label>
            <input
              id="subject-name"
              autoComplete="off"
              maxLength={MAX_SUBJECT_NAME}
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div>
            <label htmlFor="subject-code" className={labelClass}>
              Short code <span className="font-normal">(optional, for example MAT)</span>
            </label>
            <input
              id="subject-code"
              autoComplete="off"
              maxLength={MAX_SUBJECT_CODE}
              className={inputClass}
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </div>
        </div>
        {subject && (
          <div className="mt-4 max-w-sm">
            <label htmlFor="subject-category" className={labelClass}>
              Counts in a Form student&apos;s KCSE mean grade as
            </label>
            <select
              id="subject-category"
              className={inputClass}
              value={category}
              onChange={(event) => setCategory(event.target.value as KcseCategory)}
            >
              {(Object.keys(KCSE_CATEGORY_LABELS) as KcseCategory[]).map((key) => (
                <option key={key} value={key}>
                  {KCSE_CATEGORY_LABELS[key]}
                </option>
              ))}
            </select>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Mathematics and the best language always count, then the best five other subjects.
            </p>
          </div>
        )}
        {subject && (
          <label className="mt-4 flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            <span>Active (can be added to classes)</span>
          </label>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Saving..." : subject ? "Save changes" : "Add subject"}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  );
}

const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";
