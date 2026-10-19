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

### IP addresses are not logged yet

Login rate limiting (Phase B) may need client IPs. Whether and how long to
keep them will be decided then, with Kenya's Data Protection Act in mind.

### `psycopg[binary]` in production

The backend uses psycopg's pre-built binary package. psycopg's documentation
suggests a locally built package for production. To be reviewed when Render
deployment is set up.
