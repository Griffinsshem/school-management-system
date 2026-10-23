"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { AppShell, goToLogin } from "@/components/app-shell";
import {
  ErrorMessage,
  Notice,
  buttonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
} from "@/components/ui";
import { api, withReference, type Me } from "@/lib/api";
import { ROLES, formatDate, invitationStatusLabel, roleLabel } from "@/lib/labels";
import type { InvitationSummary, Member } from "@/lib/people";

const PATH = "/people";

export function People() {
  return <AppShell path={PATH}>{(me) => <PeopleContent me={me} />}</AppShell>;
}

function PeopleContent({ me }: { me: Me }) {
  const school = me.active_school;
  if (!school) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">People</h1>
        <p>
          Choose a school first on the{" "}
          <Link href="/" className="underline">
            home page
          </Link>
          .
        </p>
      </section>
    );
  }
  if (!me.permissions.includes("members.read")) {
    return (
      <section>
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">People</h1>
        <p>You do not have access to this page in {school.name}.</p>
      </section>
    );
  }
  // Keyed by school, so switching school starts this page afresh.
  return <PeopleLists key={school.id} me={me} />;
}

type Lists = { members: Member[]; invitations: InvitationSummary[] };

// What the person is being asked to confirm, if anything.
type Confirming = { kind: "member" | "invitation"; id: string } | null;

function PeopleLists({ me }: { me: Me }) {
  const router = useRouter();
  const canManage = me.permissions.includes("members.manage");
  const [lists, setLists] = useState<Lists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (): Promise<Lists | string | null> => {
    const [members, invitations] = await Promise.all([
      api<{ members: Member[] }>("/school/members"),
      api<{ invitations: InvitationSummary[] }>("/school/invitations"),
    ]);
    if (members.status === 401 || invitations.status === 401) {
      goToLogin(PATH);
      return null;
    }
    if (!members.ok) {
      return withReference(members.error);
    }
    if (!invitations.ok) {
      return withReference(invitations.error);
    }
    return { members: members.data.members, invitations: invitations.data.invitations };
  }, []);

  useEffect(() => {
    let cancelled = false;
    load().then((result) => {
      if (cancelled || result === null) {
        return;
      }
      if (typeof result === "string") {
        setError(result);
      } else {
        setLists(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function reload() {
    const result = await load();
    if (typeof result === "string") {
      setError(result);
    } else if (result !== null) {
      setLists(result);
    }
  }

  function startConfirming(next: Confirming) {
    setError(null);
    setNotice(null);
    setConfirming(next);
  }

  async function removeMember(member: Member) {
    setBusy(true);
    const result = await api(`/school/members/${member.id}/deactivate`, { method: "POST" });
    setBusy(false);
    setConfirming(null);
    if (result.status === 401) {
      goToLogin(PATH);
      return;
    }
    if (!result.ok) {
      setError(withReference(result.error));
    } else if (member.user.id === me.user.id) {
      // Removing yourself can take away your access to this page.
      router.replace("/");
      return;
    } else {
      setNotice(`${member.user.full_name} no longer has the ${roleLabel(member.role)} role.`);
    }
    await reload();
  }

  async function withdrawInvitation(invitation: InvitationSummary) {
    setBusy(true);
    const result = await api(`/school/invitations/${invitation.id}/revoke`, { method: "POST" });
    setBusy(false);
    setConfirming(null);
    if (result.status === 401) {
      goToLogin(PATH);
      return;
    }
    if (result.ok) {
      setNotice(`The invitation for ${invitation.email} was withdrawn. Its link no longer works.`);
    } else {
      setError(withReference(result.error));
    }
    await reload();
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">People</h1>
      <p className="mb-6 text-zinc-600 dark:text-zinc-400">{me.active_school?.name}</p>
      {canManage && <InviteSection schoolName={me.active_school?.name ?? ""} onInvited={reload} />}
      <ErrorMessage message={error} />
      {notice && <Notice>{notice}</Notice>}
      {!lists && !error && <p role="status">Loading...</p>}
      {lists && (
        <>
          <MembersTable
            members={lists.members}
            myUserId={me.user.id}
            canManage={canManage}
            confirming={confirming}
            busy={busy}
            onStart={(id) => startConfirming({ kind: "member", id })}
            onCancel={() => setConfirming(null)}
            onConfirm={removeMember}
          />
          <InvitationsTable
            invitations={lists.invitations}
            canManage={canManage}
            confirming={confirming}
            busy={busy}
            onStart={(id) => startConfirming({ kind: "invitation", id })}
            onCancel={() => setConfirming(null)}
            onConfirm={withdrawInvitation}
          />
        </>
      )}
    </>
  );
}

type CreatedInvitation = { email: string; role: string; url: string };

function InviteSection({ schoolName, onInvited }: { schoolName: string; onInvited: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("teacher");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // The link exists only here, in memory: it is shown once and never stored.
  const [created, setCreated] = useState<CreatedInvitation | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCreated(null);
    setPending(true);
    const result = await api<{ invitation: { email: string; role: string }; accept_url: string }>(
      "/school/invitations",
      { method: "POST", body: { email, role } },
    );
    setPending(false);
    if (result.ok) {
      setCreated({
        email: result.data.invitation.email,
        role: result.data.invitation.role,
        url: result.data.accept_url,
      });
      setEmail("");
      await onInvited();
    } else if (result.status === 422) {
      setError("Enter a valid email address.");
    } else {
      setError(withReference(result.error));
    }
  }

  return (
    <section aria-labelledby="invite-heading" className="mb-10 rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800">
      <h2 id="invite-heading" className="mb-3 text-xl font-semibold">
        Invite someone
      </h2>
      {created ? (
        <InvitationLink created={created} schoolName={schoolName} onDone={() => setCreated(null)} />
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <ErrorMessage message={error} />
          <div className="grid gap-4 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
            <div>
              <label htmlFor="invite-email" className={labelClass}>
                Email address
              </label>
              <input
                id="invite-email"
                type="email"
                inputMode="email"
                autoComplete="off"
                required
                maxLength={254}
                className={inputClass}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="invite-role" className={labelClass}>
                Role
              </label>
              <select
                id="invite-role"
                className={inputClass}
                value={role}
                onChange={(event) => setRole(event.target.value)}
              >
                {ROLES.map((code) => (
                  <option key={code} value={code}>
                    {roleLabel(code)}
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className={`${buttonClass} sm:w-auto`} disabled={pending}>
              {pending ? "Creating..." : "Create invitation link"}
            </button>
          </div>
          <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
            You will get a link to send to this person yourself. It works once and expires after
            7 days. Inviting the same person to the same role again replaces the earlier link.
          </p>
        </form>
      )}
    </section>
  );
}

function InvitationLink({
  created,
  schoolName,
  onDone,
}: {
  created: CreatedInvitation;
  schoolName: string;
  onDone: () => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";
  const role = roleLabel(created.role);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.url);
      setCopied("Link copied.");
    } catch {
      setCopied("Could not copy automatically. Select the link and copy it.");
    }
  }

  async function share() {
    try {
      await navigator.share({
        title: `Invitation to ${schoolName}`,
        text: `You are invited to join ${schoolName} as ${role}.`,
        url: created.url,
      });
    } catch {
      // The person closed the share sheet; nothing to do.
    }
  }

  return (
    <div>
      <h3 ref={headingRef} tabIndex={-1} className="mb-2 font-semibold focus:outline-none">
        Invitation link for {created.email} ({role})
      </h3>
      <p className="mb-3 text-sm">
        Send this link only to {created.email}. Anyone who has it can join {schoolName} as {role}.
        It is shown only now: if you lose it, invite the person again.
      </p>
      <label htmlFor="invitation-link" className="sr-only">
        Invitation link
      </label>
      <input
        id="invitation-link"
        readOnly
        value={created.url}
        className={`${inputClass} mb-3 font-mono text-sm`}
        onFocus={(event) => event.target.select()}
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={`${buttonClass} w-auto`} onClick={copy}>
          Copy link
        </button>
        {canShare && (
          <button type="button" className={secondaryButtonClass} onClick={share}>
            Share...
          </button>
        )}
        <button type="button" className={secondaryButtonClass} onClick={onDone}>
          Done
        </button>
      </div>
      <p role="status" className="mt-2 text-sm">
        {copied}
      </p>
    </div>
  );
}

// "Remove" turns into a question with "Yes" and "Cancel" in the same place,
// instead of a browser pop-up. Focus moves to "Yes" so keyboard users follow.
function ConfirmButtons({
  question,
  yes,
  busy,
  onConfirm,
  onCancel,
}: {
  question: string;
  yes: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const yesRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    yesRef.current?.focus();
  }, []);
  return (
    <div className="flex flex-col gap-2">
      <span>{question}</span>
      <div className="flex gap-2">
        <button
          ref={yesRef}
          type="button"
          className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-60"
          onClick={onConfirm}
          disabled={busy}
        >
          {yes}
        </button>
        <button type="button" className={`${secondaryButtonClass} py-1`} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}

type RowActions<T> = {
  canManage: boolean;
  confirming: Confirming;
  busy: boolean;
  onStart: (id: string) => void;
  onCancel: () => void;
  onConfirm: (item: T) => void;
};

const tableClass = "w-full min-w-[36rem] border-collapse text-left text-sm";
const thClass = "border-b border-zinc-300 px-3 py-2 font-medium dark:border-zinc-700";
const tdClass = "border-b border-zinc-200 px-3 py-2 align-top dark:border-zinc-800";

function MembersTable({
  members,
  myUserId,
  canManage,
  confirming,
  busy,
  onStart,
  onCancel,
  onConfirm,
}: { members: Member[]; myUserId: string } & RowActions<Member>) {
  return (
    <section aria-labelledby="members-heading" className="mb-10">
      <h2 id="members-heading" className="mb-3 text-xl font-semibold">
        Members
      </h2>
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead>
            <tr>
              <th scope="col" className={thClass}>Name</th>
              <th scope="col" className={thClass}>Email</th>
              <th scope="col" className={thClass}>Role</th>
              <th scope="col" className={thClass}>Status</th>
              {canManage && (
                <th scope="col" className={thClass}>
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => {
              const isMe = member.user.id === myUserId;
              const role = roleLabel(member.role);
              return (
                <tr key={member.id}>
                  <td className={tdClass}>
                    {member.user.full_name}
                    {isMe && <span className="text-zinc-600 dark:text-zinc-400"> (you)</span>}
                  </td>
                  <td className={tdClass}>{member.user.email}</td>
                  <td className={tdClass}>{role}</td>
                  <td className={tdClass}>{member.is_active ? "Active" : "Removed"}</td>
                  {canManage && (
                    <td className={tdClass}>
                      {!member.is_active ? null : confirming?.kind === "member" &&
                        confirming.id === member.id ? (
                        <ConfirmButtons
                          question={
                            isMe
                              ? `Remove your own ${role} role? You may lose access to this page.`
                              : `Remove ${member.user.full_name} as ${role}?`
                          }
                          yes="Yes, remove"
                          busy={busy}
                          onConfirm={() => onConfirm(member)}
                          onCancel={onCancel}
                        />
                      ) : (
                        <button
                          type="button"
                          className={`${secondaryButtonClass} py-1`}
                          aria-label={`Remove ${member.user.full_name} as ${role}`}
                          onClick={() => onStart(member.id)}
                          disabled={busy}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InvitationsTable({
  invitations,
  canManage,
  confirming,
  busy,
  onStart,
  onCancel,
  onConfirm,
}: { invitations: InvitationSummary[] } & RowActions<InvitationSummary>) {
  return (
    <section aria-labelledby="invitations-heading">
      <h2 id="invitations-heading" className="mb-3 text-xl font-semibold">
        Invitations
      </h2>
      {invitations.length === 0 ? (
        <p>No invitations yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th scope="col" className={thClass}>Email</th>
                <th scope="col" className={thClass}>Role</th>
                <th scope="col" className={thClass}>Status</th>
                <th scope="col" className={thClass}>Sent</th>
                <th scope="col" className={thClass}>Expires</th>
                {canManage && (
                  <th scope="col" className={thClass}>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {invitations.map((invitation) => (
                <tr key={invitation.id}>
                  <td className={tdClass}>{invitation.email}</td>
                  <td className={tdClass}>{roleLabel(invitation.role)}</td>
                  <td className={tdClass}>{invitationStatusLabel(invitation.status)}</td>
                  <td className={tdClass}>{formatDate(invitation.created_at)}</td>
                  <td className={tdClass}>
                    {invitation.status === "pending" ? formatDate(invitation.expires_at) : "-"}
                  </td>
                  {canManage && (
                    <td className={tdClass}>
                      {invitation.status !== "pending" ? null : confirming?.kind === "invitation" &&
                        confirming.id === invitation.id ? (
                        <ConfirmButtons
                          question={`Withdraw the invitation for ${invitation.email}? Its link will stop working.`}
                          yes="Yes, withdraw"
                          busy={busy}
                          onConfirm={() => onConfirm(invitation)}
                          onCancel={onCancel}
                        />
                      ) : (
                        <button
                          type="button"
                          className={`${secondaryButtonClass} py-1`}
                          aria-label={`Withdraw invitation for ${invitation.email}`}
                          onClick={() => onStart(invitation.id)}
                          disabled={busy}
                        >
                          Withdraw
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
