import type { Metadata } from "next";

import { Subjects } from "./subjects";

export const metadata: Metadata = { title: "Subjects" };

export default function SubjectsPage() {
  return <Subjects />;
}
