"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { canSeeFees, gradeBillsPrintPath, gradeFeesPath, termLabel, type GradeBillsToPrint } from "@/lib/fees";

import { NoFeesAccess } from "../../../../fees";
import { PrintedBillView } from "../../../../printed-bill";

// Every bill of a grade for a term, ready to print (E3): one bill per
// printed page, class by class, to send home with the students.

export function GradeBillsPrintPage() {
  const { yearId, term, grade } = useParams<{ yearId: string; term: string; grade: string }>();
  return (
    <AppShell path="/fees">
      {(me) => <Content me={me} yearId={yearId} term={Number(term)} grade={grade} />}
    </AppShell>
  );
}

function Content({ me, yearId, term, grade }: { me: Me; yearId: string; term: number; grade: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Print bills" />;
  }
  return <GradePrintView key={`${school.id}/${yearId}/${term}/${grade}`} yearId={yearId} term={term} grade={grade} />;
}

function GradePrintView({ yearId, term, grade }: { yearId: string; term: number; grade: string }) {
  const [data, setData] = useState<GradeBillsToPrint | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<GradeBillsToPrint>(`/school/fees/years/${yearId}/terms/${term}/grades/${grade}/bills/print`).then(
      (response) => {
        if (cancelled) {
          return;
        }
        if (response.status === 401) {
          goToLogin(gradeBillsPrintPath(yearId, term, grade));
        } else if (response.status === 404) {
          setNotFound(true);
        } else if (response.ok) {
          setData(response.data);
        } else {
          setError(withReference(response.error));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [yearId, term, grade]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Bills not found</h1>
        <p>
          There are no classes of this grade in that school year, or the term is not in this school.{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!data) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  const label = termLabel(data.term, data.year);
  const count = data.bills.length;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link
              href={gradeFeesPath(data.year.id, data.term.number, data.grade.code)}
              className="text-sm text-link underline underline-offset-2"
            >
              Back to {data.grade.name} fees
            </Link>
          </p>
          <h1 className="mb-1 text-[1.9375rem] leading-tight font-bold tracking-tight">
            Print {data.grade.name} bills
          </h1>
          <p className="text-muted">
            {label}: {count} bill{count === 1 ? "" : "s"}, one per page, class by class.
          </p>
        </div>
        {count > 0 && (
          <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
            Print all
          </button>
        )}
      </div>
      {count === 0 ? (
        <p>No bills have been issued for {data.grade.name} in {label} yet.</p>
      ) : (
        data.bills.map((bill, n) => (
          <PrintedBillView
            key={bill.id}
            school={data.school}
            term={data.term}
            year={data.year}
            bill={bill}
            dueOn={data.due_on}
            className={n < count - 1 ? "mb-6 print:mb-0 print:break-after-page" : ""}
          />
        ))
      )}
    </>
  );
}
