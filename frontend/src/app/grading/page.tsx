import type { Metadata } from "next";

import { GradingPage } from "./grading";

export const metadata: Metadata = { title: "Grading" };

export default function Page() {
  return <GradingPage />;
}
