"use client";

import { useEffect, useRef, type ReactNode } from "react";

// Small shared building blocks so every screen looks and behaves the same.

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center">
      <div className="w-full max-w-md rounded-lg border border-rule border-t-4 border-t-band bg-surface p-6 sm:p-8">
        <p className="mb-1 text-sm text-muted">School Management System</p>
        <h1 className="mb-6 text-[1.9375rem] leading-tight font-bold tracking-tight">{title}</h1>
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
      className="mb-4 rounded-md border-l-4 border-danger bg-danger-soft px-3 py-2 text-danger-ink focus:outline-none"
    >
      {message}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="mb-4 rounded-md border-l-4 border-ok bg-ok-soft px-3 py-2 text-ink"
    >
      {children}
    </div>
  );
}

export const inputClass =
  "block w-full rounded-md border border-field bg-surface px-3 py-2 text-base text-ink focus:border-action focus:outline-none focus:ring-2 focus:ring-action/40 read-only:bg-readonly";

export const labelClass = "mb-1 block text-sm font-medium";

const primaryButtonBase =
  "inline-flex items-center justify-center rounded-md bg-action px-4 py-2 font-semibold text-on-action hover:bg-action-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:opacity-60";

// Full width: the main button of a small form (log in, create account).
export const buttonClass = `${primaryButtonBase} w-full`;

// As wide as its text: a button beside other controls (Search, Switch).
export const inlineButtonClass = primaryButtonBase;

export const secondaryButtonClass =
  "inline-flex items-center justify-center rounded-md border border-field px-4 py-2 font-semibold hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:opacity-60";

// The "Yes, remove" button of a confirmation that removes or ends something
// (a student from a class, an invitation). Compact: it sits in the row.
export const dangerButtonClass =
  "inline-flex items-center justify-center rounded-md bg-danger px-3 py-1 font-semibold text-white hover:bg-danger-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger disabled:cursor-not-allowed disabled:opacity-60";
