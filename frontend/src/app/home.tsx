"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AppShell, goToLogin, menuLinks } from "@/components/app-shell";
import {
  ErrorMessage,
  inlineButtonClass,
  inputClass,
  labelClass,
} from "@/components/ui";
import { hasAnyMarksAccess } from "@/lib/assessments";
import { api, withReference, type Me, type School } from "@/lib/api";
import { permissionLabel, roleLabel } from "@/lib/labels";

function uniqueSchools(me: Me): School[] {
  const byId = new Map(me.memberships.map((membership) => [membership.school.id, membership.school]));
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function Home() {
  return <AppShell path="/">{(me, setMe) => <HomeContent me={me} setMe={setMe} />}</AppShell>;
}

function HomeContent({ me, setMe }: { me: Me; setMe: (me: Me) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function chooseSchool(schoolId: string) {
    setError(null);
    setPending(true);
    const result = await api<Me>("/auth/active-school", {
      method: "POST",
      body: { school_id: schoolId },
    });
    setPending(false);
    if (result.ok) {
      setMe(result.data);
    } else if (result.status === 401) {
      goToLogin("/");
    } else {
      setError(withReference(result.error));
    }
  }

  const schools = uniqueSchools(me);
  const active = me.active_school;
  const roles = active
    ? me.memberships.filter((m) => m.school.id === active.id).map((m) => roleLabel(m.role))
    : [];

  return (
    <>
      <ErrorMessage message={error} />

      {active ? (
        <ActiveSchool me={me} school={active} roles={roles} />
      ) : schools.length > 0 ? (
        <ChooseSchool me={me} schools={schools} onChoose={chooseSchool} pending={pending} />
      ) : (
        <section>
          <h1 className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">Welcome, {me.user.full_name}</h1>
          <p>
            {me.user.is_platform_admin
              ? "You are a platform administrator. School pages appear here once you are a member of a school."
              : "You are not a member of any school yet. Ask your school for an invitation link."}
          </p>
        </section>
      )}

      {active && schools.length > 1 && (
        <SwitchSchool schools={schools} activeId={active.id} onChoose={chooseSchool} pending={pending} />
      )}
    </>
  );
}

// V1: the home page is a map of the school's work, grouped the way a school
// thinks about it, showing only the pages this person can open.
const AREAS: { title: string; pages: { href: string; about: string }[] }[] = [
  {
    title: "Classes and teaching",
    pages: [
      { href: "/classes", about: "Class lists, registers, marks and report cards" },
      { href: "/attendance", about: "Which registers were taken, and term summaries" },
      { href: "/subjects", about: "The school's subjects and who teaches them" },
    ],
  },
  {
    title: "Students and staff",
    pages: [
      { href: "/students", about: "Student records and guardians" },
      { href: "/people", about: "Staff accounts and invitations" },
    ],
  },
  {
    title: "Calendar and grading",
    pages: [
      { href: "/school-year", about: "School years and their terms" },
      { href: "/grading", about: "KCSE grade boundaries and class positions" },
    ],
  },
  {
    title: "Fees",
    pages: [{ href: "/fees", about: "Fee structures and bills, by term and grade" }],
  },
];

function ActiveSchool({ me, school, roles }: { me: Me; school: School; roles: string[] }) {
  const labels = new Map(menuLinks(me).map((link) => [link.href, link.label]));
  if (hasAnyMarksAccess(me)) {
    labels.set("/grading", "Grading");
  }
  const areas = AREAS.map((area) => ({
    title: area.title,
    pages: area.pages.flatMap((page) => {
      const label = labels.get(page.href);
      return label ? [{ ...page, label }] : [];
    }),
  })).filter((area) => area.pages.length > 0);

  return (
    <section aria-labelledby="school-heading" className="mb-8">
      <div className="mb-6 flex items-center gap-4">
        <SchoolCrest name={school.name} />
        <div className="min-w-0">
          <h1 id="school-heading" className="text-[1.9375rem] leading-tight font-bold tracking-tight break-words">
            {school.name}
          </h1>
          <p className="text-muted">{school.county_name} County</p>
        </div>
      </div>
      <dl className="mb-8">
        <dt className="text-sm font-medium text-muted">Your role</dt>
        <dd className="text-lg font-semibold">{roles.join(", ")}</dd>
      </dl>

      {areas.length > 0 ? (
        <div className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
          {areas.map((area) => (
            <section key={area.title} aria-labelledby={`area-${area.pages[0].href.slice(1)}`}>
              <h2
                id={`area-${area.pages[0].href.slice(1)}`}
                className="mb-3 border-b border-rule pb-1 text-xl font-semibold"
              >
                {area.title}
              </h2>
              <ul className="space-y-3">
                {area.pages.map((page) => (
                  <li key={page.href}>
                    <Link href={page.href} className="font-semibold text-link underline underline-offset-2">
                      {page.label}
                    </Link>
                    <p className="text-sm text-muted">{page.about}</p>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <p>Nothing to open yet. More features are on the way.</p>
      )}

      {/* Closed by default: useful when someone asks "why can't I...?",
          not every time the page opens. */}
      <details className="mt-10 border-t border-rule pt-4">
        <summary className="cursor-pointer font-semibold">What your role allows</summary>
        <dl className="mt-3">
          <dt className="sr-only">You can</dt>
          <dd>
            {me.permissions.length > 0 ? (
              <ul className="list-inside list-disc space-y-1">
                {me.permissions.map((permission) => (
                  <li key={permission}>{permissionLabel(permission)}</li>
                ))}
              </ul>
            ) : (
              "Nothing yet. More features are on the way."
            )}
          </dd>
        </dl>
      </details>
    </section>
  );
}

// Kenyan schools are known by their crests: a shield with the school's
// initials (first and last word, so "Staging Demo School A" and "... B"
// differ), edged in the red margin colour. Decoration only (aria-hidden):
// the name is always written out beside it.
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return "?";
  }
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

const SHIELD = "[clip-path:polygon(0_0,100%_0,100%_68%,50%_100%,0_68%)]";

export function SchoolCrest({ name, size = "large" }: { name: string; size?: "large" | "small" }) {
  const box = size === "large" ? "h-16 w-14 text-xl" : "h-12 w-10 text-base";
  return (
    <span aria-hidden="true" className={`relative inline-block shrink-0 bg-margin ${SHIELD} ${box}`}>
      <span
        className={`absolute inset-[3px] grid place-items-center bg-crest pb-2 font-bold tracking-wide text-crest-ink ${SHIELD}`}
      >
        {initials(name)}
      </span>
    </span>
  );
}

// "Good morning" in the school's time (Kenya), whatever the computer's clock.
function greeting(name: string): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: "Africa/Nairobi" }).format(
      new Date(),
    ),
  );
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${part}, ${name}`;
}

function ChooseSchool({
  me,
  schools,
  onChoose,
  pending,
}: {
  me: Me;
  schools: School[];
  onChoose: (schoolId: string) => void;
  pending: boolean;
}) {
  const [chosen, setChosen] = useState<School | null>(null);
  const opening = pending ? chosen : null;
  const rolesAt = (schoolId: string) =>
    me.memberships.filter((m) => m.school.id === schoolId).map((m) => roleLabel(m.role));

  return (
    <section aria-labelledby="choose-heading" className="max-w-2xl">
      <p className="mb-1 text-muted">{greeting(me.user.full_name)}</p>
      <h1 id="choose-heading" className="mb-2 text-[1.9375rem] leading-tight font-bold tracking-tight">
        Choose a school
      </h1>
      <p className="mb-6">
        {schools.length === 1
          ? "Open your school to start."
          : `You belong to ${schools.length} schools. Choose one to open; you can switch later from the home page.`}
      </p>
      <ul className="grid gap-3">
        {schools.map((school) => (
          <li key={school.id}>
            <button
              type="button"
              className="group flex w-full items-center gap-4 rounded-lg border border-rule-strong bg-surface p-4 text-left hover:border-action hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:opacity-60 sm:gap-5 sm:p-5"
              onClick={() => {
                setChosen(school);
                onChoose(school.id);
              }}
              disabled={pending}
            >
              <SchoolCrest name={school.name} />
              <span className="min-w-0 flex-1">
                <span className="block text-lg leading-snug font-semibold break-words">{school.name}</span>
                <span className="block text-muted">{school.county_name} County</span>
                <span className="mt-1 block text-sm">
                  Your role: <strong className="font-semibold">{rolesAt(school.id).join(", ")}</strong>
                </span>
              </span>
              <span className="hidden shrink-0 font-semibold text-link group-hover:underline sm:block">
                {opening?.id === school.id ? "Opening..." : "Open"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p role="status" className="mt-4 text-muted">
        {opening ? `Opening ${opening.name}...` : ""}
      </p>
    </section>
  );
}

function SwitchSchool({
  schools,
  activeId,
  onChoose,
  pending,
}: {
  schools: School[];
  activeId: string;
  onChoose: (schoolId: string) => void;
  pending: boolean;
}) {
  const [selected, setSelected] = useState(activeId);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected !== activeId) {
      onChoose(selected);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-sm rounded-lg border border-rule p-4">
      <label htmlFor="school" className={labelClass}>
        Switch school
      </label>
      <div className="flex gap-2">
        <select
          id="school"
          className={inputClass}
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          {schools.map((school) => (
            <option key={school.id} value={school.id}>
              {school.name} ({school.county_name})
            </option>
          ))}
        </select>
        <button type="submit" className={inlineButtonClass} disabled={pending || selected === activeId}>
          Switch
        </button>
      </div>
    </form>
  );
}
