"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import { ErrorMessage, inlineButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { billPath, billPrintPath, canSeeFees, type Bill } from "@/lib/fees";

import { NoFeesAccess } from "../../../fees";
import { PrintedBillView } from "../../../printed-bill";

// One bill ready to print or save as a PDF (E3), with the balance from
// earlier terms and the amount due now.

export function BillPrintPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell path="/fees">{(me) => <Content me={me} billId={id} />}</AppShell>;
}

function Content({ me, billId }: { me: Me; billId: string }) {
  const school = me.active_school;
  if (!school || !canSeeFees(me)) {
    return <NoFeesAccess me={me} title="Print bill" />;
  }
  return <BillPrintView key={school.id} billId={billId} />;
}

function BillPrintView({ billId }: { billId: string }) {
  const [bill, setBill] = useState<Bill | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Bill>(`/school/fees/bills/${billId}`).then((response) => {
      if (cancelled) {
        return;
      }
      if (response.status === 401) {
        goToLogin(billPrintPath(billId));
      } else if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setBill(response.data);
      } else {
        setError(withReference(response.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [billId]);

  if (notFound) {
    return (
      <section>
        <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Bill not found</h1>
        <p>
          This bill does not exist, or it is not in this school.{" "}
          <Link href="/fees" className="text-link underline underline-offset-2">
            Back to fees
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!bill) {
    return error ? <ErrorMessage message={error} /> : <p className="text-muted">Loading...</p>;
  }

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <p className="mb-2">
            <Link href={billPath(bill.id)} className="text-sm text-link underline underline-offset-2">
              Back to {bill.student.full_name}&apos;s bill
            </Link>
          </p>
          <h1 className="text-[1.9375rem] leading-tight font-bold tracking-tight break-words">
            Print bill for {bill.student.full_name}
          </h1>
        </div>
        <button type="button" className={inlineButtonClass} onClick={() => window.print()}>
          Print
        </button>
      </div>
      <PrintedBillView school={bill.school} term={bill.term} year={bill.year} bill={bill} />
    </>
  );
}
