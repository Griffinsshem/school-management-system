import type { Metadata } from "next";

import { SchoolYear } from "./school-year";

export const metadata: Metadata = { title: "School year" };

export default function SchoolYearPage() {
  return <SchoolYear />;
}
