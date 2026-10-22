"use client";

import { useEffect, useRef, type ReactNode } from "react";

// Small shared building blocks so every screen looks and behaves the same.

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center">
      <div className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">{title}</h1>
        {children}
      </div>
    </main>
  );
}

// Announced by screen readers, and focus moves to it so keyboard users land
// on the problem. Clear the message (set it to null) before each new attempt.
export function ErrorMessage({ message }: { message: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message) {
      ref.current?.focus();
    }
  }, [message]);
  if (!message) {
    return null;
  }
  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 focus:outline-none dark:border-red-800 dark:bg-red-950 dark:text-red-100"
    >
      {message}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="mb-4 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100"
    >
      {children}
    </div>
  );
}

export const inputClass =
  "block w-full rounded-md border border-zinc-400 bg-white px-3 py-2 text-base text-zinc-900 focus:border-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-700/40 read-only:bg-zinc-100 dark:border-zinc-600 dark:bg-zinc-950 dark:text-zinc-100 dark:read-only:bg-zinc-800";

export const labelClass = "mb-1 block text-sm font-medium";

export const buttonClass =
  "inline-flex w-full items-center justify-center rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:opacity-60";

export const secondaryButtonClass =
  "inline-flex items-center justify-center rounded-md border border-zinc-400 px-4 py-2 font-medium hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-600 dark:hover:bg-zinc-800";
