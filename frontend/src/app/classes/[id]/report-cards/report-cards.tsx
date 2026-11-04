"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, Notice, inlineButtonClass, inputClass, labelClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { describeMarksError, hasAnyMarksAccess } from "@/lib/assessments";
import {
  MAX_COMMENT_LENGTH,
  commentProblem,
  printReportCardsPath,
  reportCardPath,
  reportCardsPath,
  type ClassReportCards,
  type OneReportCard,
  type ReportCard,
} from "@/lib/report-cards";
import { classResultsPath } from "@/lib/results";

import { useTerm } from "./use-term";

// A class's report cards for a term (D7): each student's overall result and
// the class teacher's comment, written here. School administrators and the
// class teacher write; principals read.

export function ReportCardsPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} classId={id} />}</AppShell>;
}

function Content({ me, classId }: { me: Me; classId: string }) {
  const school = me.active_school;
  if (!school || !hasAnyMarksAccess(me)) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Report cards</h1>
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
  return <Cards key={school.id} classId={classId} />;
}

export function CardsNotFound({ single = false }: { single?: boolean }) {
  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">
        {single ? "Report card not found" : "Report cards not found"}
      </h1>
      <p>
        {single
          ? "This student has no report card in this class, or you cannot see it."
          : "This class does not exist, or you are not its class teacher."}{" "}
        <Link href="/classes" className="underline">
          Back to the classes
        </Link>
        .
      </p>
    </section>
  );
}

function Cards({ classId }: { classId: string }) {
  const router = useRouter();
  const [term, setTerm] = useTerm();
  const [data, setData] = useState<ClassReportCards | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (term === null) {
      return;
    }
    let cancelled = false;
    api<ClassReportCards>(`/school/classes/${classId}/report-cards?${new URLSearchParams({ term: String(term) })}`).then(
      (response) => {
        if (cancelled) {
          return;
        }
        if (response.status === 401) {
          goToLogin(reportCardsPath(classId, term));
        } else if (response.status === 404) {
          setNotFound(true);
        } else if (response.ok) {
          setError(null);
          setData(response.data);
        } else {
          setData(null);
          setError(response.status === 422 ? describeMarksError(422, response.error) : withReference(response.error));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [classId, term]);

  if (notFound) {
    return <CardsNotFound />;
  }

  const written = data ? data.students.filter((s) => s.comment).length : 0;

  return (
    <>
      <p className="mb-2 flex flex-wrap gap-x-4">
        <Link href={`/classes/${classId}`} className="text-sm underline">
          Back to {data?.class.name ?? "the class"}
        </Link>
        {term !== null && (
          <Link href={classResultsPath(classId, term)} className="text-sm underline">
            Term results
          </Link>
        )}
      </p>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1 text-2xl font-semibold tracking-tight">Report cards</h1>
          {data && <p className="text-zinc-600 dark:text-zinc-400">{data.class.name}</p>}
        </div>
        {term !== null && (
          <div>
            <label htmlFor="term" className={labelClass}>
              Term
            </label>
            <select
              id="term"
              className={inputClass}
              value={term}
              onChange={(event) => {
                const next = Number(event.target.value);
                setData(null);
                setTerm(next);
                router.replace(reportCardsPath(classId, next));
              }}
            >
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  Term {n}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <ErrorMessage message={error} />

      {!data ? (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      ) : data.students.length === 0 ? (
        <p>No students in {data.class.name} yet.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm" id="comments-written">
              {written} of {data.students.length} comment{data.students.length === 1 ? "" : "s"} written.
            </p>
            <Link href={printReportCardsPath(classId, data.term.number)} className={inlineButtonClass}>
              Print all report cards
            </Link>
          </div>
          {data.can_comment && (
            <p className="mb-4 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
              Write each student&apos;s comment below, up to {MAX_COMMENT_LENGTH} characters. It appears on their
              report card for Term {data.term.number}. Leave a comment empty and save to remove it.
            </p>
          )}
          <ul className="space-y-4">
            {data.students.map((card) => (
              <li key={card.id} className="min-w-0 rounded-lg border border-zinc-200 p-4 break-words dark:border-zinc-800">
                <StudentRow
                  data={data}
                  card={card}
                  classId={classId}
                  onSaved={(next) =>
                    setData((current) =>
                      current && {
                        ...current,
                        students: current.students.map((s) => (s.id === next.id ? next : s)),
                      },
                    )
                  }
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function StudentRow({
  data,
  card,
  classId,
  onSaved,
}: {
  data: ClassReportCards;
  card: ReportCard;
  classId: string;
  onSaved: (card: ReportCard) => void;
}) {
  const overall = card.overall;
  return (
    <>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-semibold">
          {card.full_name}
          <span className="ml-2 text-sm font-normal text-zinc-600 dark:text-zinc-400">
            {card.admission_number}
            {!card.in_class && ", no longer in this class"}
          </span>
        </h2>
        <Link href={reportCardPath(classId, card.id, data.term.number)} className="text-sm underline">
          View report card<span className="sr-only"> of {card.full_name}</span>
        </Link>
      </div>
      <p className="mb-3 text-sm">
        {data.scale.kind === "kcse" ? "Mean grade" : "Overall"}:{" "}
        {overall ? (
          <>
            <span className="font-medium">{overall.grade}</span>
            {!overall.complete && " (incomplete)"}
          </>
        ) : (
          "no results yet"
        )}
        {data.show_positions && card.position != null && `, position ${card.position} of ${data.position_out_of}`}
      </p>
      {data.can_comment ? (
        <CommentForm data={data} card={card} classId={classId} onSaved={onSaved} />
      ) : card.comment ? (
        <p className="text-sm whitespace-pre-line">{card.comment.text}</p>
      ) : (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">No comment yet.</p>
      )}
    </>
  );
}

function CommentForm({
  data,
  card,
  classId,
  onSaved,
}: {
  data: ClassReportCards;
  card: ReportCard;
  classId: string;
  onSaved: (card: ReportCard) => void;
}) {
  const saved = card.comment?.text ?? "";
  const [text, setText] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fieldId = `comment-${card.id}`;
  const countId = `comment-count-${card.id}`;
  const length = text.trim().length;
  const tooLong = length > MAX_COMMENT_LENGTH;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    const problem = commentProblem(text);
    if (problem) {
      setError(problem);
      return;
    }
    setPending(true);
    const query = new URLSearchParams({ term: String(data.term.number) });
    const response = await api<OneReportCard>(`/school/classes/${classId}/report-cards/${card.id}/comment?${query}`, {
      method: "PUT",
      body: { comment: text },
    });
    setPending(false);
    if (response.status === 401) {
      goToLogin(reportCardsPath(classId, data.term.number));
    } else if (response.ok) {
      const next = response.data.student;
      setText(next.comment?.text ?? "");
      setNotice(next.comment ? `Comment saved for ${card.full_name}.` : `Comment removed for ${card.full_name}.`);
      onSaved(next);
    } else {
      setError(describeMarksError(response.status, response.error));
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}
      <label htmlFor={fieldId} className={labelClass}>
        Comment for {card.full_name}
      </label>
      <textarea
        id={fieldId}
        rows={3}
        className={inputClass}
        value={text}
        aria-describedby={countId}
        onChange={(event) => {
          setText(event.target.value);
          setNotice(null);
        }}
      />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p
          id={countId}
          className={`text-sm ${tooLong ? "font-medium text-red-800 dark:text-red-300" : "text-zinc-600 dark:text-zinc-400"}`}
        >
          {length} of {MAX_COMMENT_LENGTH} characters
          {card.comment && `. Last changed by ${card.comment.updated_by}`}
        </p>
        <button type="submit" className={inlineButtonClass} disabled={pending || text === saved}>
          {pending ? "Saving..." : "Save comment"}
          <span className="sr-only"> for {card.full_name}</span>
        </button>
      </div>
    </form>
  );
}
