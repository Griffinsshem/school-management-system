"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AppShell, goToLogin, menuLinks } from "@/components/app-shell";
import {
  ErrorMessage,
  inlineButtonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
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
        <ChooseSchool schools={schools} onChoose={chooseSchool} pending={pending} />
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
      <h1 id="school-heading" className="text-[1.9375rem] leading-tight font-bold tracking-tight break-words">
        {school.name}
      </h1>
      <p className="mb-6 text-muted">{school.county_name} County</p>
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

function ChooseSchool({
  schools,
  onChoose,
  pending,
}: {
  schools: School[];
  onChoose: (schoolId: string) => void;
  pending: boolean;
}) {
  return (
    <section aria-labelledby="choose-heading">
      <h1 id="choose-heading" className="mb-4 text-[1.9375rem] leading-tight font-bold tracking-tight">
        Choose a school
      </h1>
      <ul className="grid gap-3">
        {schools.map((school) => (
          <li key={school.id}>
            <button
              type="button"
              className={`${secondaryButtonClass} w-full justify-between`}
              onClick={() => onChoose(school.id)}
              disabled={pending}
            >
              <span>{school.name}</span>
              <span className="text-sm text-muted">{school.county_name}</span>
            </button>
          </li>
        ))}
      </ul>
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
              {school.name}
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
