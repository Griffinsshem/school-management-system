"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type ApiErrorBody } from "@/lib/api";
import { subjectMarksPath } from "@/lib/assessments";
import type { Member } from "@/lib/people";
import type { ClassSubject, ClassSubjects, Subject } from "@/lib/subjects";

// The subjects a class takes and who teaches each one (D3). Principals see
// them; school administrators also add and remove subjects and teachers.

function describeError(status: number, error: ApiErrorBody): string {
  if (status === 409 || status === 404) {
    return error.message;
  }
  if (status === 422 && error.details && error.details.length > 0) {
    return error.details.map((d) => d.message.replace(/^Value error, /, "")).join(" ");
  }
  return withReference(error);
}

export function ClassSubjectsSection({
  classId,
  className,
  canManage,
  marks,
}: {
  classId: string;
  className: string;
  canManage: boolean;
  marks: boolean;
}) {
  const path = `/school/classes/${classId}/subjects`;
  const [taken, setTaken] = useState<ClassSubject[] | null>(null);
  const [allSubjects, setAllSubjects] = useState<Subject[]>([]);
  const [teachers, setTeachers] = useState<Member[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<ClassSubjects>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(`/classes/${classId}`);
      } else if (response.ok) {
        setTaken(response.data.subjects);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, classId]);

  // For administrators: the school's subjects and active teachers to choose from.
  useEffect(() => {
    if (!canManage) {
      return;
    }
    let cancelled = false;
    api<{ subjects: Subject[] }>("/school/subjects").then((response) => {
      if (!cancelled && response.ok) {
        setAllSubjects(response.data.subjects);
      }
    });
    api<{ members: Member[] }>("/school/members").then((response) => {
      if (!cancelled && response.ok) {
        setTeachers(
          response.data.members
            .filter((m) => m.role === "teacher" && m.is_active)
            .sort((a, b) => a.user.full_name.localeCompare(b.user.full_name)),
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [canManage]);

  // Every change returns the class's subjects as they now are.
  async function send(url: string, method: "POST" | "DELETE", body: unknown, message: string): Promise<boolean> {
    setError(null);
    setNotice(null);
    setPending(true);
    const response = await api<ClassSubjects>(url, { method, body });
    setPending(false);
    if (response.status === 401) {
      goToLogin(`/classes/${classId}`);
      return false;
    }
    if (!response.ok) {
      setError(describeError(response.status, response.error));
      return false;
    }
    setTaken(response.data.subjects);
    setNotice(message);
    return true;
  }

  const takenIds = new Set((taken ?? []).map((t) => t.subject.id));
  const addable = allSubjects.filter((s) => s.is_active && !takenIds.has(s.id));

  return (
    <section aria-labelledby="class-subjects-heading" className="mb-8">
      <h2 id="class-subjects-heading" className="mb-3 text-xl font-semibold">
        Subjects
      </h2>
      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {!taken ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : taken.length === 0 ? (
        <p className="mb-3">{className} takes no subjects yet.</p>
      ) : (
        <ul className="mb-4 grid gap-3">
          {taken.map((item) => (
            <SubjectItem
              key={item.subject.id}
              item={item}
              path={`${path}/${item.subject.id}`}
              className={className}
              teachers={teachers}
              canManage={canManage}
              marksHref={marks ? subjectMarksPath(classId, item.subject.id) : null}
              pending={pending}
              send={send}
            />
          ))}
        </ul>
      )}

      {canManage && taken && (
        <AddSubject
          addable={addable}
          hasSubjects={allSubjects.length > 0}
          pending={pending}
          onAdd={(subject) =>
            send(path, "POST", { subject_id: subject.id }, `${className} now takes ${subject.name}.`)
          }
        />
      )}
    </section>
  );
}

type Send = (url: string, method: "POST" | "DELETE", body: unknown, message: string) => Promise<boolean>;

function SubjectItem({
  item,
  path,
  className,
  teachers,
  canManage,
  marksHref,
  pending,
  send,
}: {
  item: ClassSubject;
  path: string;
  className: string;
  teachers: Member[];
  canManage: boolean;
  marksHref: string | null;
  pending: boolean;
  send: Send;
}) {
  const { subject } = item;
  const [confirming, setConfirming] = useState(false);
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const yesRef = useRef<HTMLButtonElement>(null);
  const assigned = new Set(item.teachers.map((t) => t.membership_id));
  const available = teachers.filter((t) => !assigned.has(t.id));
  const selectId = `teacher-for-${subject.id}`;

  useEffect(() => {
    if (confirming) {
      yesRef.current?.focus();
    }
  }, [confirming]);

  async function addTeacher(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const teacher = available.find((t) => t.id === chosen);
    if (!teacher) {
      setError(`Choose a teacher for ${subject.name}.`);
      return;
    }
    const done = await send(
      `${path}/teachers`,
      "POST",
      { membership_id: teacher.id },
      `${teacher.user.full_name} now teaches ${subject.name} in ${className}.`,
    );
    if (done) {
      setChosen("");
    }
  }

  return (
    <li aria-label={subject.name} className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {subject.name}
            {subject.code && <span className="font-normal text-zinc-600 dark:text-zinc-400"> ({subject.code})</span>}
            {!subject.is_active && <span className="font-normal text-zinc-600 dark:text-zinc-400"> (inactive)</span>}
          </p>
          {marksHref && (
            <p className="text-sm">
              <Link href={marksHref} className="underline">
                {subject.name} marks
              </Link>
            </p>
          )}
          {item.teachers.length === 0 ? (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">No teacher yet.</p>
          ) : (
            <ul className="text-sm">
              {item.teachers.map((teacher) => (
                <li key={teacher.membership_id} className="flex flex-wrap items-center gap-2 py-0.5">
                  <span>
                    {teacher.full_name}
                    {!teacher.is_active && (
                      <span className="text-zinc-600 dark:text-zinc-400"> (no longer a teacher here)</span>
                    )}
                  </span>
                  {canManage && (
                    <button
                      type="button"
                      className={`${secondaryButtonClass} px-2 py-0.5 text-sm`}
                      aria-label={`Remove ${teacher.full_name} from ${subject.name}`}
                      onClick={() =>
                        send(
                          `${path}/teachers/${teacher.membership_id}`,
                          "DELETE",
                          undefined,
                          `${teacher.full_name} no longer teaches ${subject.name} in ${className}.`,
                        )
                      }
                      disabled={pending}
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        {canManage && !confirming && (
          <button
            type="button"
            className={`${secondaryButtonClass} py-1`}
            aria-label={`Remove ${subject.name} from ${className}`}
            onClick={() => setConfirming(true)}
            disabled={pending}
          >
            Remove subject
          </button>
        )}
      </div>

      {canManage && confirming && (
        <div className="mt-3 flex flex-col gap-2">
          <span>
            Remove {subject.name} from {className}?
            {item.teachers.length > 0 && " Its teachers in this class are removed too."}
          </span>
          <div className="flex gap-2">
            <button
              ref={yesRef}
              type="button"
              className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
              onClick={() => send(path, "DELETE", undefined, `${className} no longer takes ${subject.name}.`)}
              disabled={pending}
            >
              Yes, remove
            </button>
            <button
              type="button"
              className={`${secondaryButtonClass} py-1`}
              onClick={() => setConfirming(false)}
              disabled={pending}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {canManage && !confirming && available.length > 0 && (
        <form onSubmit={addTeacher} noValidate className="mt-3 flex max-w-md flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <label htmlFor={selectId} className={labelClass}>
              Add a teacher for {subject.name}
            </label>
            <select id={selectId} className={inputClass} value={chosen} onChange={(e) => setChosen(e.target.value)}>
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
          <div className="w-full">
            <ErrorMessage message={error} />
          </div>
        </form>
      )}
    </li>
  );
}

function AddSubject({
  addable,
  hasSubjects,
  pending,
  onAdd,
}: {
  addable: Subject[];
  hasSubjects: boolean;
  pending: boolean;
  onAdd: (subject: Subject) => Promise<boolean>;
}) {
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const subject = addable.find((s) => s.id === chosen);
    if (!subject) {
      setError("Choose a subject to add.");
      return;
    }
    if (await onAdd(subject)) {
      setChosen("");
    }
  }

  if (addable.length === 0) {
    return (
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {hasSubjects
          ? "This class already takes every active subject."
          : "This school has no subjects yet. Add them on the Subjects page."}
      </p>
    );
  }
  return (
    <form onSubmit={onSubmit} noValidate className="flex max-w-md flex-wrap items-end gap-2">
      <div className="min-w-48 flex-1">
        <label htmlFor="class-subject" className={labelClass}>
          Add a subject
        </label>
        <select id="class-subject" className={inputClass} value={chosen} onChange={(e) => setChosen(e.target.value)}>
          <option value="">Choose a subject</option>
          {addable.map((subject) => (
            <option key={subject.id} value={subject.id}>
              {subject.name}
            </option>
          ))}
        </select>
      </div>
      <button type="submit" className={inlineButtonClass} disabled={pending}>
        Add
      </button>
      <div className="w-full">
        <ErrorMessage message={error} />
      </div>
    </form>
  );
}
