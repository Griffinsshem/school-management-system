import type { Metadata } from "next";
import { Suspense } from "react";

import { Card } from "@/components/ui";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <Card title="Log in">
      {/* The form reads ?next= from the address, which is only known in the browser. */}
      <Suspense fallback={<p>Loading...</p>}>
        <LoginForm />
      </Suspense>
    </Card>
  );
}
