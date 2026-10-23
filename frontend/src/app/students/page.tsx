import type { Metadata } from "next";

import { Students } from "./students";

export const metadata: Metadata = { title: "Students" };

export default function StudentsPage() {
  return <Students />;
}
