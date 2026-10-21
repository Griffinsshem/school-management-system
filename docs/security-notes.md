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
use separate users and credentials, set up with deployment.

### `sms_app` can write to `alembic_version`

Default privileges give `sms_app` row access to every table `sms_migrator`
creates, including Alembic's `alembic_version` bookkeeping table. The API
never touches it. To be tightened if a later review finds it worthwhile.

### The development server logs query strings and IPs

Flask's built-in development server prints its own access line for each
request, including the query string and client IP. It is used only locally.
The production web server (set up with deployment) must have its access log
disabled or configured to the same rules as the app's summary line.

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
NIST recommends. This needs either an external service or a bundled list and
will be reconsidered when users can choose or change their own passwords
(invitations, B5).

### Administrative changes are logged, not yet audited

Creating a school, adding a membership and switching schools are written to
the application log with IDs only (no names or emails). Logs are not a
tamper-resistant audit trail. Refused attempts to switch into another school
appear only as `403` lines in the request log, without a dedicated warning.
A proper audit table, recording who changed what and when (and refused
attempts), is planned with roles and permissions (B4).

### The school list is not paginated

`GET /api/v1/platform/schools` returns every school. This is fine for
hundreds of schools; pagination will be added before it could grow large.

### `psycopg[binary]` in production

The backend uses psycopg's pre-built binary package. psycopg's documentation
suggests a locally built package for production. To be reviewed when Render
deployment is set up.
