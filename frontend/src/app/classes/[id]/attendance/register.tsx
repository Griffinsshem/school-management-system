"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

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
  REASONS,
  STATUSES,
  canSeeAttendance,
  formatDay,
  isDate,
  kenyaToday,
  reasonLabel,
  registerPath,
  type Reason,
  type Register as RegisterData,
  type Status,
} from "@/lib/attendance";

// The menu marks "Attendance" as the current page.
const MENU_PATH = "/attendance";

export function Register() {
  const { id } = useParams<{ id: string }>();
  const asked = useSearchParams().get("date");
  const date = isDate(asked) ? asked : kenyaToday();
  return <AppShell path={MENU_PATH}>{(me) => <Content me={me} classId={id} date={date} />}</AppShell>;
}

function Content({ me, classId, date }: { me: Me; classId: string; date: string }) {
  const school = me.active_school;
  if (!school || !canSeeAttendance(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Attendance</h1>
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
  // Keyed by school, class and day, so each starts afresh.
  return <RegisterView key={`${school.id}/${classId}/${date}`} classId={classId} date={date} />;
}

// "YYYY-MM-DD" plus or minus some days, as calendar dates.
function addDays(value: string, days: number): string {
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}

// A moment the database recorded, shown as a time in Kenya.
function formatMoment(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    timeZone: "Africa/Nairobi",
    dateStyle: "medium",
    timeStyle: "short",
  });
}

type Draft = Record<string, { status: Status; reason: Reason | null }>;

function draftFrom(register: RegisterData): Draft {
  return Object.fromEntries(
    register.marks.map((mark) => [mark.student.id, { status: mark.status, reason: mark.reason }]),
  );
}

// The API's messages, made readable (see the students page).
function describeError(status: number, error: ApiErrorBody): string {
  if (status === 422 && error.details && error.details.length > 0) {
    // One line per problem, without repeating the same one for each student.
    const messages = error.details.map((d) => d.message.replace(/^Value error, /, ""));
    return [...new Set(messages)].join(" ");
  }
  if (status === 409 || status === 403 || status === 404) {
    return error.message;
  }
  return withReference(error);
}

function RegisterView({ classId, date }: { classId: string; date: string }) {
  const router = useRouter();
  const path = `/school/classes/${classId}/attendance/${date}`;
  const today = kenyaToday();
  const [register, setRegister] = useState<RegisterData | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [notFound, setNotFound] = useState(false);
  // Why there is no register for this day (not in a term, in the future).
  const [noRegister, setNoRegister] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [dayText, setDayText] = useState(date);
  const [version, setVersion] = useState(0);
  // Someone changed the class or the register meanwhile: offer a reload.
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<RegisterData>(path).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(registerPath(classId, date));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (!response.ok && response.status === 422) {
        setNoRegister(describeError(response.status, response.error));
      } else if (response.ok) {
        setRegister(response.data);
        setDraft(draftFrom(response.data));
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path, classId, date, version]);

  function showDay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isDate(dayText)) {
      router.push(registerPath(classId, dayText));
    }
  }

  function setStatus(studentId: string, status: Status) {
    setNotice(null);
    setDraft((current) => ({
      ...current,
      // Only an absence has a reason; the person chooses it.
      [studentId]: { status, reason: status === "absent" ? current[studentId]?.reason ?? null : null },
    }));
  }

  function setReason(studentId: string, reason: Reason | null) {
    setNotice(null);
    setDraft((current) => ({ ...current, [studentId]: { status: "absent", reason } }));
  }

  async function save() {
    if (!register) {
      return;
    }
    setError(null);
    setNotice(null);
    setStale(false);
    const missing = register.marks
      .filter((mark) => draft[mark.student.id]?.status === "absent" && !draft[mark.student.id]?.reason)
      .map((mark) => mark.student.full_name);
    if (missing.length > 0) {
      setError(`Choose a reason for each absence: ${missing.join(", ")}.`);
      return;
    }
    setPending(true);
    const response = await api<RegisterData>(path, {
      method: "PUT",
      body: {
        marks: register.marks.map((mark) => ({ student_id: mark.student.id, ...draft[mark.student.id] })),
      },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(registerPath(classId, date));
    } else if (response.ok) {
      setRegister(response.data);
      setDraft(draftFrom(response.data));
      setNotice(response.status === 201 ? "Register saved." : "Changes saved.");
    } else {
      setStale(response.status === 409);
      setError(describeError(response.status, response.error));
    }
  }

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Class not found</h1>
        <p>
          This class does not exist, or it is not one of yours.{" "}
          <Link href="/attendance" className="underline">
            Back to attendance
          </Link>
          .
        </p>
      </section>
    );
  }

  const counts = { present: 0, absent: 0, late: 0 };
  for (const mark of Object.values(draft)) {
    counts[mark.status] += 1;
  }

  return (
    <>
      <p className="mb-2">
        <Link href="/attendance" className="text-sm underline">
          Back to attendance
        </Link>
      </p>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">
        {register ? `${register.class.name} register` : "Register"}
      </h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">
        {formatDay(date)}
        {register?.term_number ? `, Term ${register.term_number}` : ""}
      </p>

      <div className="mb-6 flex flex-wrap items-end gap-2">
        <form onSubmit={showDay} className="flex flex-wrap items-end gap-2" noValidate>
          <div>
            <label htmlFor="day" className={labelClass}>
              Day
            </label>
            <input
              id="day"
              type="date"
              className={inputClass}
              max={today}
              value={dayText}
              onChange={(event) => setDayText(event.target.value)}
            />
          </div>
          <button type="submit" className={secondaryButtonClass}>
            Show
          </button>
        </form>
        <Link href={registerPath(classId, addDays(date, -1))} className={secondaryButtonClass}>
          Previous day
        </Link>
        {date < today && (
          <Link href={registerPath(classId, addDays(date, 1))} className={secondaryButtonClass}>
            Next day
          </Link>
        )}
      </div>

      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}

      {noRegister ? (
        <p>{noRegister}</p>
      ) : !register ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : (
        <>
          <RegisterStatus register={register} />
          {register.marks.length === 0 ? (
            <p>No students in {register.class.name}, so there is no register to take.</p>
          ) : (
            <>
              <p className="mb-3 font-medium" aria-live="polite">
                Present {counts.present}, absent {counts.absent}, late {counts.late}
              </p>
              <ul className="mb-6 divide-y divide-zinc-200 border-y border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
                {register.marks.map(({ student }) => {
                  const mark = draft[student.id];
                  return (
                    <li key={student.id} className="py-3">
                      {register.editable ? (
                        <MarkInput
                          student={student}
                          status={mark.status}
                          reason={mark.reason}
                          onStatus={(status) => setStatus(student.id, status)}
                          onReason={(reason) => setReason(student.id, reason)}
                        />
                      ) : (
                        <div className="flex flex-wrap justify-between gap-x-4">
                          <span>
                            {student.full_name}{" "}
                            <span className="text-zinc-600 dark:text-zinc-400">({student.admission_number})</span>
                          </span>
                          <span>
                            {register.taken
                              ? `${STATUSES.find((s) => s.value === mark.status)?.label}${
                                  mark.reason ? `: ${reasonLabel(mark.reason)}` : ""
                                }`
                              : "Not marked"}
                          </span>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
              {register.editable && (
                <button type="button" className={inlineButtonClass} onClick={save} disabled={pending}>
                  {pending ? "Saving..." : register.taken ? "Save changes" : "Save register"}
                </button>
              )}
              {stale && (
                <button
                  type="button"
                  className={`${secondaryButtonClass} ml-2`}
                  onClick={() => {
                    setError(null);
                    setStale(false);
                    setRegister(null);
                    setVersion((current) => current + 1);
                  }}
                >
                  Reload
                </button>
              )}
            </>
          )}
          <p className="mt-8">
            <Link href={`/classes/${classId}/attendance/summary`} className="underline">
              Term summary for {register.class.name}
            </Link>
          </p>
        </>
      )}
    </>
  );
}

function RegisterStatus({ register }: { register: RegisterData }) {
  const lines: string[] = [];
  if (register.taken && register.taken_by && register.taken_at) {
    lines.push(`Taken by ${register.taken_by} on ${formatMoment(register.taken_at)}.`);
    if (register.updated_at && register.updated_at !== register.taken_at) {
      lines.push(`Last changed by ${register.updated_by} on ${formatMoment(register.updated_at)}.`);
    }
  } else if (register.editable) {
    lines.push("Not taken yet. Everyone starts as present: mark who is absent or late, then save.");
  } else {
    lines.push("Not taken yet.");
  }
  if (register.editable && register.teacher_can_change_until) {
    lines.push(`You can change this register until ${formatDay(register.teacher_can_change_until)}.`);
  } else if (!register.editable && register.teacher_can_change_until) {
    lines.push("This day is more than 7 days ago, so only a school administrator can change its register.");
  }
  return (
    <div className="mb-4 space-y-1">
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}

function MarkInput({
  student,
  status,
  reason,
  onStatus,
  onReason,
}: {
  student: { id: string; admission_number: string; full_name: string };
  status: Status;
  reason: Reason | null;
  onStatus: (status: Status) => void;
  onReason: (reason: Reason | null) => void;
}) {
  const name = `status-${student.id}`;
  return (
    <fieldset className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <legend className="sr-only">
        {student.full_name} ({student.admission_number})
      </legend>
      <span aria-hidden="true">
        {student.full_name} <span className="text-zinc-600 dark:text-zinc-400">({student.admission_number})</span>
      </span>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex gap-3">
          {STATUSES.map((option) => (
            <label key={option.value} className="flex items-center gap-1">
              <input
                type="radio"
                className="size-4"
                name={name}
                value={option.value}
                checked={status === option.value}
                onChange={() => onStatus(option.value)}
              />
              {option.label}
            </label>
          ))}
        </div>
        {status === "absent" && (
          <div>
            <label htmlFor={`reason-${student.id}`} className="sr-only">
              Reason
            </label>
            <select
              id={`reason-${student.id}`}
              className={`${inputClass} py-1`}
              value={reason ?? ""}
              onChange={(event) => onReason((event.target.value || null) as Reason | null)}
            >
              <option value="">Choose a reason</option>
              {REASONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </fieldset>
  );
}
