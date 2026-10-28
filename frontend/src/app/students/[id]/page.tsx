import type { Metadata } from "next";
import { Suspense } from "react";

import { StudentPage } from "./student";

export const metadata: Metadata = { title: "Student" };

// The student ID comes from the address, which Next.js only knows when the
// page is requested; Suspense lets the rest be prepared ahead.
export default function StudentRoute() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <StudentPage />
    </Suspense>
  );
}
