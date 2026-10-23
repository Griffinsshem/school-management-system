"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { ErrorMessage, secondaryButtonClass } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";

// The frame of every page that needs a login: it asks the API who is logged
// in, sends the person to the login page if nobody is (or the session has
// ended), and shows the header with navigation and "Log out".

export function loginUrl(next: string): string {
  return `/login?next=${encodeURIComponent(next)}&expired=1`;
}

// Next.js keeps recently visited pages, hidden, in the browser tab so going
// back is instant. When a session ends, everything the previous person saw
// must go, so these load the login page afresh instead.
export function goToLogin(next: string) {
  window.location.replace(loginUrl(next));
}

function logOutCompleted() {
  window.location.replace("/login");
}

export function AppShell({
  path,
  children,
}: {
  path: string;
  children: (me: Me, setMe: (me: Me) => void) => ReactNode;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Me>("/auth/me").then((result) => {
      if (cancelled) {
        return;
      }
      if (result.ok) {
        setMe(result.data);
      } else if (result.status === 401) {
        goToLogin(path);
      } else {
        setError(withReference(result.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  async function logOut() {
    setError(null);
    setPending(true);
    const result = await api("/auth/logout", { method: "POST" });
    if (result.ok || result.status === 401) {
      logOutCompleted();
      return;
    }
    setPending(false);
    setError(withReference(result.error));
  }

  if (!me) {
    return (
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        {error ? <ErrorMessage message={error} /> : <p role="status">Loading...</p>}
      </main>
    );
  }

  const links = [
    { href: "/", label: "Home", show: true },
    { href: "/students", label: "Students", show: me.permissions.includes("students.read") },
    { href: "/people", label: "People", show: me.permissions.includes("members.read") },
  ].filter((link) => link.show);

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <p className="font-semibold">School Management System</p>
            <nav aria-label="Main">
              <ul className="flex gap-4">
                {links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      aria-current={link.href === path ? "page" : undefined}
                      className="rounded px-1 underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-700 aria-[current=page]:font-semibold aria-[current=page]:underline"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              <span className="sr-only">Logged in as </span>
              {me.user.full_name}
            </p>
            <button type="button" className={secondaryButtonClass} onClick={logOut} disabled={pending}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
        <ErrorMessage message={error} />
        {children(me, setMe)}
      </main>
    </div>
  );
}
