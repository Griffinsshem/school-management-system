import type { Metadata } from "next";
import { Suspense } from "react";

import { Attendance } from "./attendance";

export const metadata: Metadata = { title: "Attendance" };

// The day comes from the address (?date=), which is only known in the browser.
export default function AttendancePage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <Attendance />
    </Suspense>
  );
}
