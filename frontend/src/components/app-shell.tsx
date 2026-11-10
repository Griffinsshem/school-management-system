"use client";

import Link from "next/link";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ErrorMessage } from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { confirmLeave } from "@/lib/unsaved-changes";

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
  // A request that was still on its way when the person clicked "Log out"
  // comes back 401 once the session has ended. That is not an expired
  // session: the logout itself decides where to go.
  if (loggingOut) {
    return;
  }
  window.location.replace(loginUrl(next));
}

// The pages a person can open, in menu order. The home page groups the same
// links (see app/home.tsx), so both always agree on who sees what.
export function menuLinks(me: Me): { href: string; label: string }[] {
  const can = (permission: string) => me.permissions.includes(permission);
  return [
    { href: "/", label: "Home", show: true },
    { href: "/school-year", label: "School year", show: can("academics.read") },
    { href: "/classes", label: "Classes", show: can("classes.read") || can("classes.read_own") },
    { href: "/attendance", label: "Attendance", show: can("attendance.read") || can("attendance.record_own") },
    { href: "/subjects", label: "Subjects", show: can("subjects.read") },
    { href: "/students", label: "Students", show: can("students.read") },
    { href: "/people", label: "People", show: can("members.read") },
    { href: "/fees", label: "Fees", show: can("fees.read") },
  ]
    .filter((link) => link.show)
    .map(({ href, label }) => ({ href, label }));
}

// Set while "Log out" is in progress (one tab, one page at a time).
let loggingOut = false;

// A light outline button that reads on the dark band.
const bandButtonClass =
  "inline-flex items-center justify-center rounded-md border border-band-muted px-3 py-1.5 font-semibold text-band-ink hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-band-ink disabled:cursor-not-allowed disabled:opacity-60";

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
  const [menuOpen, setMenuOpen] = useState(false);
  // Not a fixed id: Next.js keeps visited pages (hidden) in the document,
  // and an id must be unique in it.
  const menuId = useId();

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
    if (!confirmLeave()) {
      return; // Unsaved work on the page (D8).
    }
    setError(null);
    setPending(true);
    loggingOut = true;
    const result = await api("/auth/logout", { method: "POST" });
    if (result.ok || result.status === 401) {
      logOutCompleted();
      return;
    }
    loggingOut = false;
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

  const links = menuLinks(me);

  const school = me.active_school?.name;
  const linkClass =
    "block rounded px-1 py-1 text-band-ink underline-offset-[6px] decoration-margin decoration-[3px] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-band-ink aria-[current=page]:font-semibold aria-[current=page]:underline sm:py-0";

  return (
    <div className="flex flex-1 flex-col">
      {/* V1: a dark band with the school's name, so people always know which
          school they are working in. Two rows on purpose (D8): the name and
          the account on top, the menu below, so a long menu never wraps
          unpredictably. On a phone the menu folds away behind "Menu". */}
      <header className="bg-band text-band-ink print:hidden">
        <div className="mx-auto max-w-4xl px-4 pt-3 pb-2">
          {/* The title never breaks inside a word ("Manageme / nt" at 320 px,
              seen after H1): its box is at least as wide as its longest word
              and starts from nothing (flex-1), so when the title and the
              buttons cannot share a line, Menu and Log out move below it.
              Without a school the product's name is the title, smaller on
              phones so it usually still fits on one line with them. */}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-w-min flex-1">
              <p className={`${school ? "text-xl" : "text-base sm:text-xl"} leading-tight font-bold break-words`}>
                {school ?? "School Management System"}
              </p>
              {school ? <p className="text-sm text-band-muted">School Management System</p> : null}
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-3">
              <p className="hidden text-sm text-band-muted sm:block">
                <span className="sr-only">Logged in as </span>
                {me.user.full_name}
              </p>
              <button
                type="button"
                className={`${bandButtonClass} sm:hidden`}
                aria-expanded={menuOpen}
                aria-controls={menuId}
                onClick={() => setMenuOpen((open) => !open)}
              >
                Menu
              </button>
              <button type="button" className={bandButtonClass} onClick={logOut} disabled={pending}>
                Log out
              </button>
            </div>
          </div>
          <nav id={menuId} aria-label="Main" className={`mt-2 ${menuOpen ? "block" : "hidden"} sm:block`}>
            <p className="mb-1 text-sm text-band-muted sm:hidden">
              <span className="sr-only">Logged in as </span>
              {me.user.full_name}
            </p>
            <ul className="-mx-1 flex flex-col gap-x-4 sm:flex-row sm:flex-wrap sm:gap-y-1">
              {links.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={link.href === path ? "page" : undefined}
                    className={linkClass}
                    onClick={() => setMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      {/* The red line down the left of the page, like the margin of an
          exercise book: decoration only, so not on phones or paper. */}
      <div className="mx-auto flex w-full max-w-4xl flex-1 px-4">
        <main className="w-full min-w-0 py-8 sm:border-l-2 sm:border-margin sm:pl-6 print:border-0 print:pl-0">
          <ErrorMessage message={error} />
          {children(me, setMe)}
        </main>
      </div>
    </div>
  );
}
