"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  Card,
  ErrorMessage,
  buttonClass,
  inputClass,
  labelClass,
  secondaryButtonClass,
} from "@/components/ui";
import { api, withReference, type Me, type School } from "@/lib/api";
import { roleLabel } from "@/lib/labels";

type Invitation = {
  email: string;
  role: string;
  expires_at: string;
  school: School;
  has_account: boolean;
};

type State =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "error"; message: string }
  | { kind: "ready"; token: string; invitation: Invitation; me: Me | null };

// The link looks like /invitations/accept#token=... The part after "#" never
// leaves the browser, so the token is not written to any server's logs. The
// page keeps it in this tab's session storage (so a reload or a detour via the
// login page still works) and removes it from the address bar at once.
const STORAGE_KEY = "sms.invitation_token";

// Fallback for when session storage is unavailable (for example some private
// windows): the token then survives only until the page is reloaded.
let tokenInMemory: string | null = null;

function readToken(): string | null {
  const fromLink = new URLSearchParams(window.location.hash.slice(1)).get("token");
  if (fromLink) {
    window.history.replaceState(null, "", window.location.pathname);
    tokenInMemory = fromLink;
    try {
      window.sessionStorage.setItem(STORAGE_KEY, fromLink);
    } catch {
      // Kept in memory only.
    }
    return fromLink;
  }
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) ?? tokenInMemory;
  } catch {
    return tokenInMemory;
  }
}

function forgetToken() {
  tokenInMemory = null;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to remove.
  }
}

const NOT_VALID = 404;
const MIN_PASSWORD = 12;
const MAX_PASSWORD = 128;

async function loadState(): Promise<State> {
  const token = readToken();
  if (!token) {
    return { kind: "invalid" };
  }
  const [preview, me] = await Promise.all([
    api<{ invitation: Invitation }>("/invitations/preview", { method: "POST", body: { token } }),
    api<Me>("/auth/me"),
  ]);
  if (preview.ok) {
    return { kind: "ready", token, invitation: preview.data.invitation, me: me.ok ? me.data : null };
  }
  if (preview.status === NOT_VALID || preview.status === 422) {
    forgetToken();
    return { kind: "invalid" };
  }
  return { kind: "error", message: withReference(preview.error) };
}

export function AcceptInvitation() {
  const [state, setState] = useState<State>({ kind: "loading" });

  // Runs in the browser, where the address and session storage are available.
  useEffect(() => {
    let cancelled = false;
    loadState().then((next) => {
      if (!cancelled) {
        setState(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function reload() {
    setState(await loadState());
  }

  if (state.kind === "loading") {
    return (
      <Card title="Accept invitation">
        <p role="status">Loading...</p>
      </Card>
    );
  }
  if (state.kind === "invalid") {
    return (
      <Card title="This link is not valid">
        <p>
          The invitation may have expired, been used already or been withdrawn. Ask the school for
          a new link.
        </p>
      </Card>
    );
  }
  if (state.kind === "error") {
    return (
      <Card title="Accept invitation">
        <ErrorMessage message={state.message} />
      </Card>
    );
  }
  return <Ready token={state.token} invitation={state.invitation} me={state.me} onChanged={reload} />;
}

function Ready({
  token,
  invitation,
  me,
  onChanged,
}: {
  token: string;
  invitation: Invitation;
  me: Me | null;
  onChanged: () => Promise<void>;
}) {
  const expires = new Date(invitation.expires_at).toLocaleDateString(undefined, {
    dateStyle: "long",
  });
  const summary = (
    <p className="mb-6">
      <strong>{invitation.school.name}</strong> has invited <strong>{invitation.email}</strong> to
      join as <strong>{roleLabel(invitation.role)}</strong>. The invitation expires on {expires}.
    </p>
  );

  if (me && me.user.email !== invitation.email) {
    return (
      <Card title="Accept invitation">
        {summary}
        <WrongAccount email={me.user.email} onLoggedOut={onChanged} />
      </Card>
    );
  }
  if (me) {
    return (
      <Card title="Accept invitation">
        {summary}
        <AcceptAsExistingUser token={token} />
      </Card>
    );
  }
  if (invitation.has_account) {
    return (
      <Card title="Accept invitation">
        {summary}
        <p className="mb-4">This email address already has an account. Log in to accept.</p>
        <Link href="/login?next=%2Finvitations%2Faccept" className={buttonClass}>
          Log in
        </Link>
      </Card>
    );
  }
  return (
    <Card title="Create your account">
      {summary}
      <CreateAccount token={token} email={invitation.email} />
    </Card>
  );
}

function WrongAccount({ email, onLoggedOut }: { email: string; onLoggedOut: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function logOut() {
    setError(null);
    setPending(true);
    const result = await api("/auth/logout", { method: "POST" });
    if (result.ok || result.status === 401) {
      await onLoggedOut();
      return;
    }
    setPending(false);
    setError(withReference(result.error));
  }

  return (
    <>
      <ErrorMessage message={error} />
      <p className="mb-4">
        You are logged in as <strong>{email}</strong>, but this invitation is for a different
        email address. Log out first, then continue here.
      </p>
      <button type="button" className={secondaryButtonClass} onClick={logOut} disabled={pending}>
        Log out
      </button>
    </>
  );
}

function AcceptAsExistingUser({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function accept() {
    setError(null);
    setPending(true);
    const result = await api("/invitations/accept", { method: "POST", body: { token } });
    if (result.ok) {
      forgetToken();
      router.replace("/");
      return;
    }
    setPending(false);
    setError(withReference(result.error));
  }

  return (
    <>
      <ErrorMessage message={error} />
      <button type="button" className={buttonClass} onClick={accept} disabled={pending}>
        {pending ? "Accepting..." : "Accept invitation"}
      </button>
    </>
  );
}

function CreateAccount({ token, email }: { token: string; email: string }) {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!fullName.trim()) {
      setError("Enter your full name.");
      return;
    }
    if (password.length < MIN_PASSWORD || password.length > MAX_PASSWORD) {
      setError(`Choose a password of ${MIN_PASSWORD} to ${MAX_PASSWORD} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setPending(true);
    const result = await api("/invitations/accept", {
      method: "POST",
      body: { token, full_name: fullName, password },
    });
    if (result.ok) {
      forgetToken();
      router.replace("/");
      return;
    }
    setPending(false);
    if (result.status === NOT_VALID) {
      forgetToken();
    }
    const fieldMessages = result.error.details?.map((detail) => detail.message) ?? [];
    setError(fieldMessages.length > 0 ? fieldMessages.join(" ") : withReference(result.error));
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <ErrorMessage message={error} />
      <div className="mb-4">
        <label htmlFor="email" className={labelClass}>
          Email address
        </label>
        {/* Read-only, but lets password managers save the new password for this email. */}
        <input id="email" type="email" autoComplete="username" readOnly value={email} className={inputClass} />
      </div>
      <div className="mb-4">
        <label htmlFor="full-name" className={labelClass}>
          Full name
        </label>
        <input
          id="full-name"
          name="full_name"
          autoComplete="name"
          required
          maxLength={200}
          className={inputClass}
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
        />
      </div>
      <div className="mb-4">
        <label htmlFor="new-password" className={labelClass}>
          Password
        </label>
        <input
          id="new-password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD}
          maxLength={MAX_PASSWORD}
          aria-describedby="password-hint"
          className={inputClass}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <p id="password-hint" className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          {MIN_PASSWORD} to {MAX_PASSWORD} characters. A short sentence is easy to remember.
        </p>
      </div>
      <div className="mb-6">
        <label htmlFor="confirm-password" className={labelClass}>
          Type the password again
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          required
          className={inputClass}
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </div>
      <button type="submit" className={buttonClass} disabled={pending}>
        {pending ? "Creating account..." : "Create account and join"}
      </button>
    </form>
  );
}
