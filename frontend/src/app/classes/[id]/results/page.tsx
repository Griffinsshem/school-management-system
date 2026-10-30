import type { Metadata } from "next";
import { Suspense } from "react";

import { ClassResultsPage } from "./class-results";

export const metadata: Metadata = { title: "Term results" };

// The class and the term come from the address, which Next.js only knows when the page is
// requested; Suspense lets the rest be prepared ahead.
export default function Page() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <ClassResultsPage />
    </Suspense>
  );
}
