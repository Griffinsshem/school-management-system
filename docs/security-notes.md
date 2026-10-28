# Security notes

This file records security decisions and known findings as the project
evolves. It describes what is actually implemented. It is not a compliance
statement.

## Decisions in place

- **Secrets come only from environment variables.** `.env` files are excluded
  from Git; `.env.example` files contain placeholders only.
- **The backend refuses to start with unsafe configuration.** A missing or
  short (under 32 characters) `SECRET_KEY`, or a missing `DATABASE_URL`, stops
  startup. If `APP_ENV` is unset, production checks apply.
- **Errors never expose internals.** All API errors are JSON. Unexpected
  errors return a generic message; details go only to the server log.
- **Request bodies are limited to 1 MB.** Larger requests receive `413`.
- **The health endpoint reveals nothing internal.** It returns only
  `{"status": "ok"}`.
- **Dev servers listen on 127.0.0.1 only.** They are not reachable from other
  devices on the network unless explicitly overridden for one session.
- **Least-privilege database users.** The API connects as `sms_app`, which can
  only read and write rows. Only `sms_migrator` can change the schema, and it
  is used only by migrations. Neither is a superuser. Tests verify that
  `sms_app` is refused when it tries to create a table.
- **Database access is restricted to the project's users.** Other users on
  the PostgreSQL server cannot connect to `sms_dev` or `sms_test`.
- **Database passwords are never displayed or typed.** They are generated
  into `backend/.env` (mode 600) and PostgreSQL receives only SCRAM-SHA-256
  hashes.
- **Tests cannot touch a non-test database.** The app refuses to start in
  testing mode unless every database name ends in `_test`.
- **The readiness check reveals nothing internal.** It returns only
  `{"status": "ok"}` or `{"status": "unavailable"}`; details go to the log.
- **Every request has an ID, and logs leave out personal data.** The ID is
  returned in `X-Request-ID`, included in error bodies and stamped on every
  log line. An incoming ID is reused only if it is 8 to 64 letters, digits,
  `-` or `_`, so it cannot forge log lines or tamper with headers. The
  per-request summary records method, path, status and duration only: never
  query strings, bodies, headers, cookies or IP addresses. Control characters
  in the path are escaped so a crafted URL cannot fake a log line.
- **Passwords are stored only as Argon2id hashes** (19 MiB memory,
  2 iterations, 1 thread: one of OWASP's recommended configurations, chosen
  to fit a 512 MB server). Passwords must be 12 to 128 characters; there are
  no composition rules. Hash parameters can be raised later, and old hashes
  are detected for upgrade.
- **Platform administrators can only be created from the terminal.** No API
  endpoint can grant the role, and the command never accepts the password as
  an argument or prints it.
- **Emails are unique regardless of letter case**, enforced by a database
  check constraint as well as application code.
- **Login sessions are server-side and revocable.** The browser holds a
  random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` with
  the `__Host-` prefix in production); the database holds only its SHA-256
  hash, so a leaked database cannot be turned into working cookies. Every
  login issues a new token (no session fixation). Sessions end after
  30 minutes idle or 8 hours in total; logout deletes the session, and a
  deactivated user's sessions are deleted on their next request.
- **Failed logins reveal nothing.** Wrong password, unknown email and
  deactivated account all return the same `401` message, and an unknown
  email still runs a full Argon2id check so response times match.
- **Login attempts are rate-limited** to 10 failures per account and 50 per
  IP address within 15 minutes (`429` with `Retry-After`). There is no
  permanent lockout, so an attacker cannot lock a real user out for long.
- **Cross-site request forgery (CSRF) is blocked in three layers**, following
  OWASP: `SameSite=Lax` cookies, JSON-only request bodies (an HTML form on
  another site cannot send JSON), and a check that any `Origin` header on a
  state-changing request matches `FRONTEND_ORIGIN`.
- **Request bodies are validated with Pydantic.** Unknown fields are refused,
  and validation errors name the field without repeating the submitted value,
  so passwords are never echoed or logged.
- **A request's school comes only from the server-side session.** The
  active school is set only after checking for an active membership in an
  active school, and that check is repeated on every request, so revoking a
  membership or deactivating a school takes effect immediately. Every
  inaccessible school gets the same `403`, so other schools' IDs cannot be
  probed. Code that touches school data must use `current_school()` or
  `school_required`, never an ID from the request.
- **Platform administrators have no automatic access to school data.** They
  can create and list schools, but reading a school's records needs a
  membership in that school. This limits the damage if an administrator
  account is compromised.
- **Schools and memberships are deactivated, never deleted.** The database
  refuses to delete a user or school that has memberships, so records cannot
  be lost by accident.
- **Permissions are explicit and checked on the server.** Each role maps to
  a list of permissions in code, with nothing granted by default, and every
  school endpoint declares the permission it needs. An unknown permission
  name stops the app from starting. The permissions sent to the browser in
  `/me` are for display only.
- **IDs in URLs are looked up only inside the active school.** A record from
  another school gets the same `404` as one that does not exist.
- **A school cannot lose its last school admin.** Membership changes in a
  school are serialized by locking the school's row, so two simultaneous
  requests cannot remove each other.
- **The audit trail is append-only for the API.** The migration removes
  `sms_app`'s UPDATE, DELETE and TRUNCATE rights on `audit_events`, and tests
  prove the database refuses them. Successful changes are recorded in the
  same transaction as the change; refusals (wrong school, missing
  permission, platform access) are recorded on their own. Events hold IDs
  only, never names or emails.
- **Students are isolated by the database itself.** PostgreSQL Row-Level
  Security limits `sms_app` to the rows of the school set for the current
  transaction, for reads and for writes, independently of the application's
  own school filter. With no school set, no rows are visible. The setting is
  transaction-local, so pooled connections carry nothing between requests,
  and `sms_app` cannot disable the policy. Tests run directly against the
  database as `sms_app`, and the endpoints were shown to stay isolated with
  the application's filter removed.
- **Children's data is kept to a minimum.** Student records hold an admission
  number, a name and an optional date of birth. Teachers have no access to
  students until classes exist, so they will only see the children they
  teach. Responses, logs and audit events never include a child's details
  beyond what the endpoint is for; validation errors never echo them.
- **People join only by invitation.** Invitation tokens are random 256-bit
  values stored only as SHA-256 hashes, used once, valid for 7 days and
  revocable. The link carries the token after `#`, so it never reaches
  server logs, and the API receives it only in a JSON body. Every unusable
  link gets the same `404`. Accepting locks the invitation, so it cannot be
  used twice concurrently. An existing account gains a role only when its
  owner is logged in; a different logged-in user is refused.
- **One narrow, tested exception to Row-Level Security.** Invitations are
  under Row-Level Security, but someone accepting one has no school yet.
  The database function `invitation_by_token_hash` runs as the schema owner
  and returns only the invitation whose token hash matches exactly; it
  cannot list or search. Only `sms_app` may call it, and its `search_path`
  is fixed. Tests probe it with empty, wildcard, partial and injected input.
- **The browser talks only to the frontend's own address.** Next.js forwards
  `/api/...` to Flask, so the `HttpOnly` session cookie is first-party and
  never visible to page scripts. Flask's address (`API_ORIGIN`) is a
  server-only setting, never `NEXT_PUBLIC_`.
- **Every page is sent with security headers**: `X-Frame-Options: DENY`
  (no embedding, against clickjacking), `X-Content-Type-Options: nosniff`, a
  strict `Referrer-Policy` (`no-referrer` on the invitation page) and a
  `Permissions-Policy` turning off camera, microphone and location.
  `X-Powered-By` is not sent.
- **After login, only addresses on this site are followed.** `?next=` must
  be a path on this site, so the login page cannot send people elsewhere.
- **Invitation tokens stay out of addresses.** The page removes `#token=...`
  from the address bar as soon as it loads and keeps the token only in that
  tab's session storage until it is used. It is sent to the API only in a
  JSON body.
- **Invitation links are shown once.** The People page shows a new link
  only until "Done" or a reload; it is never stored in the browser. Lost
  links are replaced by inviting the person again.
- **Nothing private stays in the browser tab.** Next.js keeps recently
  visited pages hidden in the tab. Password fields are cleared as soon as
  they are used, and logging out (or a session ending) loads the login page
  afresh, so the previous person's pages are gone even on a shared computer.
  A browser test checks both.
- **Student searches stay out of the browser history.** The Students page
  keeps the search text in memory and sends it only to the API; the page's
  address stays `/students`. Searches run on Enter or "Search", not on every
  keystroke. Dates of birth are shown as calendar dates, never shifted by
  time zones.
- **The interface hides what a person cannot do, but the API decides.** A
  principal sees no invite or remove buttons, and a browser test also
  confirms the API refuses them directly.
- **Forwarded client IPs are trusted only from configured proxies.**
  `X-Forwarded-For` is ignored unless `TRUSTED_PROXY_COUNT` is set, so
  clients cannot fake their IP to dodge rate limits.
- **CI runs with read-only permissions and no secrets.** Third-party GitHub
  Actions are pinned to exact commit IDs, so their code cannot change without
  a reviewed commit here. Checkout does not keep Git credentials.
- **CI blocks known high-severity vulnerabilities in production
  dependencies** (`npm audit --omit=dev`).
- **Commits use a GitHub no-reply email** so personal email addresses are not
  published in this public repository.

## Rules for future work

- **Caching (frontend):** never cache per-user or per-school data with
  `"use cache"` unless the cache is keyed to that user and school.
- **Never commit real student, parent or staff data.** Seed data must be
  clearly fake and labelled as such.
- **Every new school-owned table gets Row-Level Security in its own
  migration**, with the same `school_isolation` policy as `students`, and
  tests in the style of `tests/test_row_level_security.py` that query the
  database directly as `sms_app`.

## Known findings

### `braces` advisory GHSA-vfj7-8cjw-p6xm (recorded 2026-10-18)

- **Where:** `frontend` development dependencies only, via
  `eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` →
  `micromatch` → `braces`.
- **Risk:** a crafted glob pattern can crash the linter process. The linter
  only runs on patterns we write, and `npm audit --omit=dev` reports
  0 vulnerabilities, so nothing affected ships to users.
- **Why not fixed:** no patched `braces` version exists, and npm's suggested
  fix downgrades `eslint-config-next` to 14.x, two major versions behind our
  Next.js 16.
- **Action:** re-run `npm audit` whenever dependencies are updated.

### ESLint 9 is deprecated

The Next.js 16.4.2 template installs ESLint 9. It is kept until Next.js's
template and plugins support ESLint 10. No vulnerability is reported for it.

### Local database users share passwords across dev and test

`sms_app` and `sms_migrator` each use one password for both `sms_dev` and
`sms_test`. This is acceptable on a single developer machine. Production will
use separate users and credentials; staging already does (on Neon, with
generated passwords; see [deployment.md](deployment.md)).

### `sms_app` can write to `alembic_version`

Default privileges give `sms_app` row access to every table `sms_migrator`
creates, including Alembic's `alembic_version` bookkeeping table. The API
never touches it. To be tightened if a later review finds it worthwhile.

### The development server logs query strings and IPs

Flask's built-in development server prints its own access line for each
request, including the query string and client IP. It is used only locally.
The production web server (set up with deployment) must have its access log
disabled or configured to the same rules as the app's summary line.

This matters more since the Students page: a search sends part of a child's
name in the query string (`/api/v1/school/students?q=...`). The page never
puts it in its own address, so it stays out of browser history, but the
development server's access line shows it.

On staging, gunicorn's access log is off, and Render's attempt to turn it
back on is blocked (checked 2026-10-24; see [deployment.md](deployment.md)).
Vercel's own request logs have not been checked yet. If they keep query
strings, move the search into a request body (a small API change) before
real schools use the system.

### Rate limiting stores only hashed emails and IPs

Failed logins are counted per account and per IP address. Neither the email
nor the IP is stored: each is replaced by an HMAC keyed with `SECRET_KEY`,
and only the last 15 minutes count. A successful login deletes that
account's records; older records are deleted by `flask prune-sessions`, which
must be scheduled when the app is deployed (until then they accumulate as
meaningless hashes). This is data minimisation with Kenya's Data Protection
Act in mind, not a legal review. Changing `SECRET_KEY` simply resets the
counters.

### Rate limiting can let a few extra attempts through

Counting and recording failures are separate database steps, so many
simultaneous requests can exceed the limits by a small number. This does not
meaningfully help a password-guessing attacker. A stricter version is
possible later if monitoring shows a need.

### No breached-password check yet

Passwords are not yet checked against lists of known breached passwords, as
NIST recommends. People now choose their own passwords when accepting an
invitation, so this matters more. It needs either an external service (such
as Have I Been Pwned's range API) or a bundled list, and is deferred until
one of those is approved.

### Invitation links are shared by hand

There is no email delivery yet: the inviter copies the link and sends it,
for example by WhatsApp or SMS. Anyone who obtains the link before the
invitee can accept it and create the account. Single use, 7-day expiry,
revocation and the audit trail limit the damage; email delivery can be
added once a provider is chosen.

### Unknown invitation tokens are logged, not audited

The preview and accept endpoints need no login. Refused reuse of a real
invitation is audited, but made-up tokens are only logged as warnings: the
audit trail is never pruned, so recording them would let anyone fill the
database. These endpoints are not rate-limited; guessing a 256-bit token is
not feasible, and password hashing only runs for a valid token.

### Audit trail limits

- The audit table cannot be changed through the API, but the schema owner
  (`sms_migrator`) and the database superuser can still alter it. Shipping
  events to separate storage is a later step.
- How long audit events are kept has not been decided. They contain IDs,
  which are still personal data under Kenya's Data Protection Act; a
  retention period is to be set before real schools use the system.
- Logins, logouts and the automatic choice of school at login are not
  audited; only explicit school switches are. Failed logins are counted for
  rate limiting but not audited.
- The migration names the runtime user `sms_app`. A production database
  must use the same name, or the REVOKE must be adjusted.

### Only the frontend may call the API (B11)

Every request reaches gunicorn from `127.0.0.1` (Render's proxy inside the
container), and Render's address is public, so the API could not tell
visitors apart: one person could have blocked logins for everyone. Since B11
the frontend adds a shared secret (`PROXY_SHARED_SECRET`) and the visitor's
address to every API request; the API refuses requests without the secret
(`403`, health checks excepted, constant-time comparison) and trusts the
address only with it. Measured on staging on 2026-10-26: each visitor is
counted separately, forged headers are ignored, and direct requests to Render
are refused ([deployment.md](deployment.md#client-ip-addresses)).

What remains:

- Anyone who learns the secret can call the API directly and choose the
  address it counts. It lives only in Vercel's and Render's settings; change
  it if it may have leaked.
- The address comes from Vercel's `X-Forwarded-For`, which Vercel replaces.
  A self-hosted Next.js server passes on whatever the visitor sent (checked
  2026-10-22), so `src/proxy.ts` uses it only on Vercel or where
  `TRUST_X_FORWARDED_FOR=1` is set deliberately.
- In development no secret is set, the API accepts direct requests, and
  every request comes from 127.0.0.1 anyway.

### Requests without an `Origin` header pass the CSRF check

The API refuses data-changing requests whose `Origin` is another site, but
lets requests with no `Origin` through, so tools such as curl work. Browsers
send `Origin` on these requests, and the session cookie is `SameSite=Lax`,
so a page on another site still cannot act with a visitor's session.

### No Content Security Policy yet

A Content Security Policy would limit the damage of any script-injection
bug, which matters because the invitation page keeps a token in session
storage. React escapes all text it displays and the app adds no HTML of its
own, which removes the common causes. A policy with per-request nonces, as
Next.js recommends, is planned as a separate change.

### Row-Level Security covers students, invitations, academic years, terms, classes, class teachers, enrolments and attendance only

`memberships` and `audit_events` carry a `school_id` but are not under
Row-Level Security: memberships must be read across schools to list a user's
own schools at login, and audit events include refusals that belong to no
school. Both are protected by the application layer (and the audit trail is
append-only). `users`, `sessions` and `schools` are not school-owned.

### Attendance corrections: the last save wins

Two people correcting the same register at the same moment are handled one
after the other (the register row is locked while it is saved), and the
second save replaces the first. Both are recorded in the audit trail, mark
by mark. Taking a new register twice at once cannot happen: the database
keeps one register per class per day and the second save is refused.

### Student search is not indexed for large schools

Search matches part of a name with `ILIKE`, which scans the school's
students. That is fast for thousands of students per school; a trigram index
can be added if a school grows far beyond that.

### The school list is not paginated

`GET /api/v1/platform/schools` returns every school. This is fine for
hundreds of schools; pagination will be added before it could grow large.

### `psycopg[binary]` in production

The backend uses psycopg's pre-built binary package. psycopg's documentation
suggests a locally built package for production. Staging on Render uses the
binary package; to be reviewed before production.
