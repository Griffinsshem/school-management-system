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
import {
  MAX_GUARDIAN_EMAIL,
  MAX_GUARDIAN_NAME,
  MAX_GUARDIANS_PER_STUDENT,
  MAX_PHONE_INPUT,
  RELATIONSHIPS,
  canManageGuardians,
  canReadGuardians,
  formatPhone,
  relationshipLabel,
  type FoundGuardian,
  type LinkedGuardian,
  type Relationship,
  type StudentGuardians,
} from "@/lib/guardians";
import { formatBirthDate, type Student } from "@/lib/students";

// The menu marks "Students" as the current page.
const MENU_PATH = "/students";

export function StudentPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path={MENU_PATH}>{(me) => <Content me={me} studentId={id} />}</AppShell>;
}

function Content({ me, studentId }: { me: Me; studentId: string }) {
  const school = me.active_school;
  if (!school || !me.permissions.includes("students.read")) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Student</h1>
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
    <StudentView
      key={school.id}
      studentId={studentId}
      readGuardians={canReadGuardians(me)}
      manageGuardians={canManageGuardians(me)}
    />
  );
}

// The API's messages, made readable (see the students page). They never
// repeat the phone number or email that was sent.
function describeError(status: number, error: ApiErrorBody): string {
  if (status === 422 && error.details && error.details.length > 0) {
    const messages = error.details.map((d) => d.message.replace(/^Value error, /, ""));
    return [...new Set(messages)].join(" ");
  }
  if (status === 409 || status === 404) {
    return error.message;
  }
  return withReference(error);
}

function StudentView({
  studentId,
  readGuardians,
  manageGuardians,
}: {
  studentId: string;
  readGuardians: boolean;
  manageGuardians: boolean;
}) {
  const [student, setStudent] = useState<Student | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ student: Student }>(`/school/students/${studentId}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(`/students/${studentId}`);
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setStudent(response.data.student);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [studentId]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Student not found</h1>
        <p>
          This student does not exist in this school.{" "}
          <Link href="/students" className="underline">
            Back to the students
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!student) {
    return error ? <ErrorMessage message={error} /> : <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>;
  }

  return (
    <>
      <p className="mb-2">
        <Link href="/students" className="text-sm underline">
          Back to the students
        </Link>
      </p>
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">{student.full_name}</h1>
      <dl className="mb-8 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
        <dt className="text-zinc-600 dark:text-zinc-400">Admission no.</dt>
        <dd>{student.admission_number}</dd>
        <dt className="text-zinc-600 dark:text-zinc-400">Date of birth</dt>
        <dd>{formatBirthDate(student.date_of_birth)}</dd>
        <dt className="text-zinc-600 dark:text-zinc-400">Status</dt>
        <dd>{student.is_active ? "Active" : "Inactive"}</dd>
      </dl>
      {readGuardians && <Guardians studentId={studentId} canManage={manageGuardians} />}
    </>
  );
}

type Mode = { kind: "add" } | { kind: "edit"; guardianId: string } | { kind: "remove"; guardianId: string } | null;

function Guardians({ studentId, canManage }: { studentId: string; canManage: boolean }) {
  const path = `/school/students/${studentId}/guardians`;
  const [data, setData] = useState<StudentGuardians | null>(null);
  const [version, setVersion] = useState(0);
  const [mode, setMode] = useState<Mode>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<StudentGuardians>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(`/students/${studentId}`);
      } else if (response.ok) {
        setData(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, studentId, version]);

  function changed(message: string) {
    setMode(null);
    setError(null);
    setNotice(message);
    setVersion((current) => current + 1);
  }

  function open(next: Mode) {
    setError(null);
    setNotice(null);
    setMode(next);
  }

  async function send(method: "PATCH" | "DELETE", guardian: LinkedGuardian, body: unknown, message: string) {
    setError(null);
    setBusy(true);
    const response = await api(`${path}/${guardian.id}`, { method, body });
    setBusy(false);
    if (response.status === 401) {
      goToLogin(`/students/${studentId}`);
    } else if (response.ok) {
      changed(message);
    } else {
      setError(describeError(response.status, response.error));
    }
  }

  const guardians = data?.guardians ?? [];
  const full = guardians.length >= MAX_GUARDIANS_PER_STUDENT;
  return (
    <section aria-labelledby="guardians-heading">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <h2 id="guardians-heading" className="text-xl font-semibold">
          Guardians
        </h2>
        {canManage && data && !full && mode?.kind !== "add" && (
          <button type="button" className={inlineButtonClass} onClick={() => open({ kind: "add" })}>
            Add a guardian
          </button>
        )}
      </div>

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {mode?.kind === "add" && data && (
        <AddGuardian
          path={path}
          student={data.student}
          onDone={changed}
          onCancel={() => setMode(null)}
        />
      )}

      {!data ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : guardians.length === 0 ? (
        <p>No guardians recorded yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 border-y border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {guardians.map((guardian) => (
            <li key={guardian.id} className="py-3" aria-label={guardian.full_name}>
              {mode?.kind === "edit" && mode.guardianId === guardian.id ? (
                <EditGuardian
                  path={path}
                  guardian={guardian}
                  onDone={changed}
                  onCancel={() => setMode(null)}
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="font-medium">{guardian.full_name}</span>
                    <span className="text-zinc-600 dark:text-zinc-400">{relationshipLabel(guardian.relationship)}</span>
                    {guardian.is_primary && (
                      <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-900 dark:bg-blue-950 dark:text-blue-100">
                        Primary contact
                      </span>
                    )}
                  </div>
                  <p className="mt-1 break-words">
                    <a href={`tel:${guardian.phone}`} className="underline">
                      {formatPhone(guardian.phone)}
                    </a>
                    {guardian.email && <span className="ml-3">{guardian.email}</span>}
                  </p>
                  {canManage && mode?.kind === "remove" && mode.guardianId === guardian.id ? (
                    <div className="mt-2 flex flex-col gap-2">
                      <span>
                        Remove {guardian.full_name} from {data.student.full_name}? Their record stays for any other
                        children.
                      </span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
                          onClick={() =>
                            send("DELETE", guardian, undefined, `Removed ${guardian.full_name} from ${data.student.full_name}.`)
                          }
                          disabled={busy}
                        >
                          Yes, remove
                        </button>
                        <button type="button" className={`${secondaryButtonClass} py-1`} onClick={() => setMode(null)} disabled={busy}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    canManage && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {!guardian.is_primary && (
                          <button
                            type="button"
                            className={`${secondaryButtonClass} py-1`}
                            aria-label={`Make ${guardian.full_name} the primary contact`}
                            onClick={() =>
                              send("PATCH", guardian, { is_primary: true }, `${guardian.full_name} is now the primary contact.`)
                            }
                            disabled={busy}
                          >
                            Make primary
                          </button>
                        )}
                        <button
                          type="button"
                          className={`${secondaryButtonClass} py-1`}
                          aria-label={`Edit ${guardian.full_name}`}
                          onClick={() => open({ kind: "edit", guardianId: guardian.id })}
                          disabled={busy}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={`${secondaryButtonClass} py-1`}
                          aria-label={`Remove ${guardian.full_name}`}
                          onClick={() => open({ kind: "remove", guardianId: guardian.id })}
                          disabled={busy}
                        >
                          Remove
                        </button>
                      </div>
                    )
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && full && (
        <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
          A student can have at most {MAX_GUARDIANS_PER_STUDENT} guardians. Remove one to add another.
        </p>
      )}
    </section>
  );
}

function RelationshipSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: Relationship | "";
  onChange: (value: Relationship | "") => void;
}) {
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        Relationship to the student
      </label>
      <select
        id={id}
        className={inputClass}
        value={value}
        onChange={(event) => onChange(event.target.value as Relationship | "")}
      >
        <option value="">Choose</option>
        {RELATIONSHIPS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function PrimaryCheckbox({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" className="size-4" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      Make this the primary contact
    </label>
  );
}

// Adding starts with the phone number: a guardian already recorded (a
// sibling's parent) is linked, not added a second time.
function AddGuardian({
  path,
  student,
  onDone,
  onCancel,
}: {
  path: string;
  student: { id: string; full_name: string };
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [step, setStep] = useState<"phone" | "found" | "new">("phone");
  const [found, setFound] = useState<FoundGuardian | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [relationship, setRelationship] = useState<Relationship | "">("");
  const [primary, setPrimary] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function find(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!phone.trim()) {
      setError("Enter the guardian's mobile number.");
      return;
    }
    setPending(true);
    const response = await api<{ guardian: FoundGuardian }>("/school/guardians/lookup", {
      method: "POST",
      body: { phone },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(`/students/${student.id}`);
    } else if (response.ok) {
      setFound(response.data.guardian);
      setStep("found");
    } else if (response.status === 404) {
      setStep("new");
    } else {
      setError(describeError(response.status, response.error));
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!relationship) {
      setError("Choose the relationship to the student.");
      return;
    }
    const body =
      step === "found" && found
        ? { guardian_id: found.id, relationship, is_primary: primary }
        : { full_name: fullName, phone, email: email.trim() || null, relationship, is_primary: primary };
    setPending(true);
    const response = await api(step === "found" ? `${path}/link` : path, { method: "POST", body });
    setPending(false);
    if (response.status === 401) {
      goToLogin(`/students/${student.id}`);
    } else if (response.ok) {
      const name = step === "found" && found ? found.full_name : fullName.trim();
      onDone(`Added ${name} as a guardian of ${student.full_name}.`);
    } else {
      setError(describeError(response.status, response.error));
    }
  }

  const alreadyLinked = found?.students.some((s) => s.id === student.id) ?? false;
  return (
    <section
      aria-labelledby="add-guardian-heading"
      className="mb-6 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h3 id="add-guardian-heading" ref={headingRef} tabIndex={-1} className="mb-1 text-lg font-semibold focus:outline-none">
        Add a guardian for {student.full_name}
      </h3>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Start with the mobile number: a parent already recorded for a brother or sister is linked, not added twice.
      </p>
      <ErrorMessage message={error} />

      {step === "phone" ? (
        <form onSubmit={find} className="flex max-w-xl flex-wrap items-end gap-2" noValidate>
          <div className="min-w-48 flex-1">
            <label htmlFor="guardian-phone" className={labelClass}>
              Mobile number
            </label>
            <input
              id="guardian-phone"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              placeholder="0712 345 678"
              maxLength={MAX_PHONE_INPUT}
              className={inputClass}
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
          </div>
          <button type="submit" className={inlineButtonClass} disabled={pending}>
            {pending ? "Looking..." : "Find"}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </form>
      ) : (
        <form onSubmit={save} className="grid max-w-xl gap-4" noValidate>
          {step === "found" && found ? (
            <p role="status">
              <span className="font-medium">{found.full_name}</span>, {formatPhone(found.phone)},{" "}
              {alreadyLinked
                ? `is already a guardian of ${student.full_name}.`
                : found.students.length > 0
                  ? `is already recorded as a guardian of ${found.students.map((s) => s.full_name).join(", ")}.`
                  : "is already recorded."}
            </p>
          ) : (
            <>
              <p role="status">
                No guardian has the number {phone.trim()} yet. Add their details.
              </p>
              <div>
                <label htmlFor="guardian-name" className={labelClass}>
                  Full name
                </label>
                <input
                  id="guardian-name"
                  autoComplete="off"
                  maxLength={MAX_GUARDIAN_NAME}
                  className={inputClass}
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="guardian-email" className={labelClass}>
                  Email (optional)
                </label>
                <input
                  id="guardian-email"
                  type="email"
                  autoComplete="off"
                  maxLength={MAX_GUARDIAN_EMAIL}
                  className={inputClass}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </div>
            </>
          )}
          {!alreadyLinked && (
            <>
              <RelationshipSelect id="guardian-relationship" value={relationship} onChange={setRelationship} />
              <PrimaryCheckbox checked={primary} onChange={setPrimary} />
            </>
          )}
          <div className="flex flex-wrap gap-2">
            {!alreadyLinked && (
              <button type="submit" className={inlineButtonClass} disabled={pending}>
                {pending ? "Saving..." : step === "found" && found ? `Link ${found.full_name}` : "Add guardian"}
              </button>
            )}
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => {
                setError(null);
                setStep("phone");
              }}
              disabled={pending}
            >
              Use another number
            </button>
            <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

// Name, phone and email belong to the guardian (for every child they are
// linked to); the relationship belongs to this student's link.
function EditGuardian({
  path,
  guardian,
  onDone,
  onCancel,
}: {
  path: string;
  guardian: LinkedGuardian;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const [fullName, setFullName] = useState(guardian.full_name);
  const [phone, setPhone] = useState(formatPhone(guardian.phone));
  const [email, setEmail] = useState(guardian.email ?? "");
  const [relationship, setRelationship] = useState<Relationship | "">(guardian.relationship);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const details: Record<string, string | null> = {};
    if (fullName.trim() !== guardian.full_name) {
      details.full_name = fullName;
    }
    if (phone.trim() !== formatPhone(guardian.phone)) {
      details.phone = phone;
    }
    if ((email.trim() || null) !== guardian.email) {
      details.email = email.trim() || null;
    }
    setPending(true);
    if (Object.keys(details).length > 0) {
      const response = await api(`/school/guardians/${guardian.id}`, { method: "PATCH", body: details });
      if (!response.ok) {
        setPending(false);
        if (response.status === 401) {
          goToLogin(window.location.pathname);
        } else {
          setError(describeError(response.status, response.error));
        }
        return;
      }
    }
    if (relationship && relationship !== guardian.relationship) {
      const response = await api(`${path}/${guardian.id}`, { method: "PATCH", body: { relationship } });
      if (!response.ok) {
        setPending(false);
        setError(describeError(response.status, response.error));
        return;
      }
    }
    setPending(false);
    onDone(`Saved changes to ${fullName.trim()}.`);
  }

  return (
    <form onSubmit={save} className="grid max-w-xl gap-4" noValidate aria-label={`Edit ${guardian.full_name}`}>
      <ErrorMessage message={error} />
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Name, number and email change for every student this guardian is linked to.
      </p>
      <div>
        <label htmlFor={`edit-name-${guardian.id}`} className={labelClass}>
          Full name
        </label>
        <input
          id={`edit-name-${guardian.id}`}
          ref={firstRef}
          autoComplete="off"
          maxLength={MAX_GUARDIAN_NAME}
          className={inputClass}
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor={`edit-phone-${guardian.id}`} className={labelClass}>
          Mobile number
        </label>
        <input
          id={`edit-phone-${guardian.id}`}
          type="tel"
          inputMode="tel"
          autoComplete="off"
          maxLength={MAX_PHONE_INPUT}
          className={inputClass}
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor={`edit-email-${guardian.id}`} className={labelClass}>
          Email (optional)
        </label>
        <input
          id={`edit-email-${guardian.id}`}
          type="email"
          autoComplete="off"
          maxLength={MAX_GUARDIAN_EMAIL}
          className={inputClass}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <RelationshipSelect id={`edit-relationship-${guardian.id}`} value={relationship} onChange={setRelationship} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={inlineButtonClass} disabled={pending}>
          {pending ? "Saving..." : "Save changes"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancel
        </button>
      </div>
    </form>
  );
}
