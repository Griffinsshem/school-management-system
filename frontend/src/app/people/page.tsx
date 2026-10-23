import type { Metadata } from "next";

import { People } from "./people";

export const metadata: Metadata = { title: "People" };

export default function PeoplePage() {
  return <People />;
}
