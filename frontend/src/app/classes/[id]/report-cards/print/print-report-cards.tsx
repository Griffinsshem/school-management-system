"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { describeMarksError, hasAnyMarksAccess } from "@/lib/assessments";
import { printReportCardsPath, reportCardsPath, type ClassReportCards } from "@/lib/report-cards";

import { ReportCardView } from "../report-card-view";
import { CardsNotFound } from "../report-cards";
import { useTerm } from "../use-term";

// Every report card of a class and term (D7), one per printed page.

export function PrintReportCardsPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/classes">{(me) => <Content me={me} classId={id} />}</AppShell>;
}

function Content({ me, classId }: { me: Me; classId: string }) {
  if (!me.active_school || !hasAnyMarksAccess(me)) {
    return <CardsNotFound />;
  }
  return <AllCards key={me.active_school.id} classId={classId} />;
}

function AllCards({ classId }: { classId: string }) {
  const [term] = useTerm();
  const [data, setData] = useState<ClassReportCards | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (term === null) {
      return;
    }
    let cancelled = false;
    const query = new URLSearchParams({ term: String(term) });
    api<ClassReportCards>(`/school/classes/${classId}/report-cards?${query}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(printReportCardsPath(classId, term));
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
  }, [classId, term]);

  if (notFound) {
    return <CardsNotFound />;
  }
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link href={reportCardsPath(classId, term ?? undefined)} className="text-sm text-link underline underline-offset-2">
              Back to the report cards
            </Link>
          </p>
          <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight">Print report cards</h1>
          {data && (
            <p className="text-muted">
              {data.class.name}, Term {data.term.number}: {data.students.length} report card
              {data.students.length === 1 ? "" : "s"}, one per page.
            </p>
          )}
        </div>
        {data && data.students.length > 0 && (
          <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
            Print all
          </button>
        )}
      </div>
      <ErrorMessage message={error} />
      {!data ? (
        !error && <p className="text-muted">Loading...</p>
      ) : data.students.length === 0 ? (
        <p>No students in {data.class.name} yet.</p>
      ) : (
        <div className="space-y-8 print:space-y-0">
          {data.students.map((card) => (
            <div key={card.id} className="break-inside-avoid print:break-after-page">
              <ReportCardView data={data} card={card} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
