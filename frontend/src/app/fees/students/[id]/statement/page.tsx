import type { Metadata } from "next";
import { Suspense } from "react";

import { StatementPage } from "./statement";

export const metadata: Metadata = { title: "Fee statement" };

// The student comes from the address, which Next.js only knows when the page is
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
      <StatementPage />
    </Suspense>
  );
}
