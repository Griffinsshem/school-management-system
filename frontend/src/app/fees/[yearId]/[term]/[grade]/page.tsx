import type { Metadata } from "next";
import { Suspense } from "react";

import { GradeFeesPage } from "./grade-fees";

export const metadata: Metadata = { title: "Grade fees" };

// The year, term and grade come from the address, which Next.js only knows
// when the page is requested; Suspense lets the rest be prepared ahead.
export default function Page() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <GradeFeesPage />
    </Suspense>
  );
}
