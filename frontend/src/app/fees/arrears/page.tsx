import type { Metadata } from "next";
import { Suspense } from "react";

import { StudentsOwingPage } from "./students-owing";

export const metadata: Metadata = { title: "Students owing" };

// The filters come from the address (?grade=, ?class=, ...), which Next.js
// only knows when the page is requested; Suspense lets the rest be prepared
// ahead.
export default function Page() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <StudentsOwingPage />
    </Suspense>
  );
}
