import type { Metadata } from "next";
import { Suspense } from "react";

import { Summary } from "./summary";

export const metadata: Metadata = { title: "Attendance summary" };

// The class and term come from the address, which is only known when the
// page is requested.
export default function SummaryPage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <Summary />
    </Suspense>
  );
}
