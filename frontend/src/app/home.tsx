"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  ErrorMessage,
  buttonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
} from "@/components/ui";
import { api, withReference, type Me, type School } from "@/lib/api";
import { permissionLabel, roleLabel } from "@/lib/labels";

const SESSION_ENDED = "/login?next=%2F&expired=1";

function uniqueSchools(me: Me): School[] {
  const byId = new Map(me.memberships.map((membership) => [membership.school.id, membership.school]));
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function Home() {
  const router = useRouter();
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
        router.replace(SESSION_ENDED);
      } else {
        setError(withReference(result.error));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

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
      router.replace(SESSION_ENDED);
    } else {
      setError(withReference(result.error));
    }
  }

  async function logOut() {
    setError(null);
    setPending(true);
    const result = await api("/auth/logout", { method: "POST" });
    if (result.ok || result.status === 401) {
      router.replace("/login");
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

  const schools = uniqueSchools(me);
  const active = me.active_school;
  const roles = active
    ? me.memberships.filter((m) => m.school.id === active.id).map((m) => roleLabel(m.role))
    : [];

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <p className="font-semibold">School Management System</p>
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

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
        <ErrorMessage message={error} />

        {active ? (
          <ActiveSchool school={active} roles={roles} permissions={me.permissions} />
        ) : schools.length > 0 ? (
          <ChooseSchool schools={schools} onChoose={chooseSchool} pending={pending} />
        ) : (
          <section>
            <h1 className="mb-2 text-2xl font-semibold tracking-tight">Welcome, {me.user.full_name}</h1>
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
      </main>
    </div>
  );
}

function ActiveSchool({
  school,
  roles,
  permissions,
}: {
  school: School;
  roles: string[];
  permissions: string[];
}) {
  return (
    <section aria-labelledby="school-heading" className="mb-8">
      <h1 id="school-heading" className="text-2xl font-semibold tracking-tight">
        {school.name}
      </h1>
      <p className="mb-6 text-zinc-600 dark:text-zinc-400">{school.county_name} County</p>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <dt className="mb-1 text-sm font-medium text-zinc-600 dark:text-zinc-400">Your role</dt>
          <dd>{roles.join(", ")}</dd>
        </div>
        <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <dt className="mb-1 text-sm font-medium text-zinc-600 dark:text-zinc-400">You can</dt>
          <dd>
            {permissions.length > 0 ? (
              <ul className="list-inside list-disc">
                {permissions.map((permission) => (
                  <li key={permission}>{permissionLabel(permission)}</li>
                ))}
              </ul>
            ) : (
              "Nothing yet. More features are on the way."
            )}
          </dd>
        </div>
      </dl>
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
      <h1 id="choose-heading" className="mb-4 text-2xl font-semibold tracking-tight">
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
              <span className="text-sm text-zinc-600 dark:text-zinc-400">{school.county_name}</span>
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
    <form onSubmit={onSubmit} className="max-w-sm rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
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
        <button type="submit" className={`${buttonClass} w-auto`} disabled={pending || selected === activeId}>
          Switch
        </button>
      </div>
    </form>
  );
}
