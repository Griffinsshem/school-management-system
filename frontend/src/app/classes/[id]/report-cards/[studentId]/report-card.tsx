"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { describeMarksError, hasAnyMarksAccess } from "@/lib/assessments";
import { reportCardPath, reportCardsPath, type OneReportCard } from "@/lib/report-cards";

import { ReportCardView } from "../report-card-view";
import { CardsNotFound } from "../report-cards";
import { useTerm } from "../use-term";

// One student's report card (D7), ready to print or save as a PDF from the
// browser's print dialog.

export function ReportCardPage() {
  const { id, studentId } = useParams<{ id: string; studentId: string }>();
  return (
    <AppShell path="/classes">
      {(me) => <Content me={me} classId={id} studentId={studentId} />}
    </AppShell>
  );
}

function Content({ me, classId, studentId }: { me: Me; classId: string; studentId: string }) {
  if (!me.active_school || !hasAnyMarksAccess(me)) {
    return <CardsNotFound single />;
  }
  return <Card key={me.active_school.id} classId={classId} studentId={studentId} />;
}

function Card({ classId, studentId }: { classId: string; studentId: string }) {
  const [term] = useTerm();
  const [data, setData] = useState<OneReportCard | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (term === null) {
      return;
    }
    let cancelled = false;
    const query = new URLSearchParams({ term: String(term) });
    api<OneReportCard>(`/school/classes/${classId}/report-cards/${studentId}?${query}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(reportCardPath(classId, studentId, term));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setData(response.data);
      } else {
        setError(response.status === 422 ? describeMarksError(422, response.error) : withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [classId, studentId, term]);

  if (notFound) {
    return <CardsNotFound single />;
  }
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link href={reportCardsPath(classId, term ?? undefined)} className="text-sm underline">
              Back to the report cards
            </Link>
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">Report card</h1>
        </div>
        {data && (
          <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
            Print
          </button>
        )}
      </div>
      <ErrorMessage message={error} />
      {data ? (
        <ReportCardView data={data} card={data.student} />
      ) : (
        !error && <p className="text-zinc-600 dark:text-zinc-400">Loading...</p>
      )}
    </>
  );
}
