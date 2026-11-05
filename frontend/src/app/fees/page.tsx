import type { Metadata } from "next";
import { Suspense } from "react";

import { Fees } from "./fees";

export const metadata: Metadata = { title: "Fees" };

// The year and term come from the address (?year=&term=), which is only
// known in the browser.
export default function FeesPage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <p role="status">Loading...</p>
        </main>
      }
    >
      <Fees />
    </Suspense>
  );
}
