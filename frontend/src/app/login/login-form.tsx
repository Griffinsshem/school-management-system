"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorMessage, Notice, buttonClass, inputClass, labelClass } from "@/components/ui";
import { api, withReference } from "@/lib/api";
import { safeNext } from "@/lib/safe-next";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const expired = searchParams.get("expired") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const result = await api("/auth/login", { method: "POST", body: { email, password } });
    if (result.ok) {
      router.replace(next);
      return;
    }
    setPending(false);
    setPassword("");
    if (result.status === 429) {
      const minutes = Math.max(1, Math.ceil((result.retryAfter ?? 60) / 60));
      setError(
        `Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`,
      );
    } else if (result.status === 401 || result.status === 422) {
      // The same message for every kind of mistake, as the API does.
      setError("Invalid email or password.");
    } else {
      setError(withReference(result.error));
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      {expired && <Notice>Your session has ended. Please log in again.</Notice>}
      <ErrorMessage message={error} />
      <div className="mb-4">
        <label htmlFor="email" className={labelClass}>
          Email address
        </label>
        <input
          id="email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="username"
          required
          maxLength={254}
          className={inputClass}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="mb-6">
        <label htmlFor="password" className={labelClass}>
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          className={inputClass}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      <button type="submit" className={buttonClass} disabled={pending}>
        {pending ? "Logging in..." : "Log in"}
      </button>
      <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
        New here? You join a school by invitation: ask the school for a link.
      </p>
    </form>
  );
}
