import type { Metadata } from "next";

import { AcceptInvitation } from "./accept-invitation";

export const metadata: Metadata = { title: "Accept invitation" };

export default function AcceptInvitationPage() {
  return <AcceptInvitation />;
}
