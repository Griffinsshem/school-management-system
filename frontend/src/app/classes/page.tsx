import type { Metadata } from "next";

import { Classes } from "./classes";

export const metadata: Metadata = { title: "Classes" };

export default function ClassesPage() {
  return <Classes />;
}
