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

### `psycopg[binary]` in production

The backend uses psycopg's pre-built binary package. psycopg's documentation
suggests a locally built package for production. To be reviewed when Render
deployment is set up.
