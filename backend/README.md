# Backend

Flask REST API for the School Management System. All endpoints live under
`/api/v1`.

## Setup

Requires Python 3.12 and a local PostgreSQL 16 server. Run from the
`backend/` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
chmod 600 .env
```

Generate a secret key directly into `.env` (it is never printed):

```bash
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')|" .env
```

Create the database users and databases, set their passwords and apply
migrations by following [docs/database.md](../docs/database.md).

Activate the virtual environment (`source .venv/bin/activate`) in every new
terminal before working on the backend.

## Run

```bash
flask --app app run
```

The API listens on `http://127.0.0.1:5000`.

```bash
curl http://127.0.0.1:5000/api/v1/health/ready
# {"status":"ok"}
```

## Test and lint

```bash
pytest
ruff check .
ruff format --check .
```

Tests use the `sms_test` database and migrate it themselves. They read only
`TEST_DATABASE_URL` and `TEST_MIGRATION_DATABASE_URL` (from the environment,
or else from `.env`) and refuse to run against a database whose name does not
end in `_test`.

## Configuration

| Variable                      | Purpose                                                         |
|-------------------------------|-----------------------------------------------------------------|
| `APP_ENV`                     | `development` or `production`. If unset, production checks apply. |
| `SECRET_KEY`                  | At least 32 random characters. The app refuses to start otherwise. |
| `LOG_LEVEL`                   | `DEBUG`, `INFO` (default), `WARNING` or `ERROR`. Invalid values stop startup. |
| `DATABASE_URL`                | API connection as `sms_app` (rows only).                        |
| `MIGRATION_DATABASE_URL`      | Migration connection as `sms_migrator` (schema owner).          |
| `TEST_DATABASE_URL`           | Test connection as `sms_app` to `sms_test`.                     |
| `TEST_MIGRATION_DATABASE_URL` | Test migration connection as `sms_migrator` to `sms_test`.      |
| `FRONTEND_ORIGIN`             | The frontend's origin, e.g. `https://app.example.com`. Required in production (https); defaults to `http://127.0.0.1:3000` in development. |
| `TRUSTED_PROXY_COUNT`         | Reverse proxies whose `X-Forwarded-For` is trusted (0 to 5, default 0). |

The app refuses to start if `SECRET_KEY` or `DATABASE_URL` is missing, so a
misconfigured server fails loudly instead of running with unsafe settings.

## Endpoints

| Method | Path                   | Response                                          |
|--------|------------------------|---------------------------------------------------|
| GET    | `/api/v1/health`       | `200 {"status":"ok"}`                             |
| GET    | `/api/v1/health/ready` | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |
| POST   | `/api/v1/auth/login`   | `200 {"user": {...}}` and a session cookie; `401`, `422` or `429` |
| POST   | `/api/v1/auth/logout`  | `204`; ends the session and clears the cookie     |
| GET    | `/api/v1/auth/me`      | `200` with the user, their memberships and active school; or `401` |
| POST   | `/api/v1/auth/active-school` | `200` (same body as `/me`), `403`, `401` or `422` |
| POST   | `/api/v1/platform/schools` | Platform admin only: `201 {"school": {...}}`, `409` (code taken), `422`, `401` or `403` |
| GET    | `/api/v1/platform/schools` | Platform admin only: `200 {"schools": [...]}`, `401` or `403` |
| GET    | `/api/v1/school/members` | Needs `members.read`: `200 {"members": [...]}` for the active school; `401` or `403` |
| POST   | `/api/v1/school/members/{id}/deactivate` | Needs `members.manage`: `200 {"member": {...}}`, `404`, `409` (last school admin), `401` or `403` |
| GET    | `/api/v1/school/students` | Needs `students.read`: `200 {"students": [...], "page", "per_page", "total"}`; `422` for bad query parameters |
| POST   | `/api/v1/school/students` | Needs `students.manage`: `201 {"student": {...}}`, `409` (admission number taken), `422` |
| GET    | `/api/v1/school/students/{id}` | Needs `students.read`: `200 {"student": {...}}` or `404` |
| PATCH  | `/api/v1/school/students/{id}` | Needs `students.manage`: `200`, `404`, `409` or `422` |
| POST   | `/api/v1/school/students/{id}/deactivate` | Needs `students.manage`: `200` or `404` |

Errors are always JSON in the form
`{"error": {"code": "...", "message": "...", "request_id": "..."}}` and never
include stack traces. Validation errors (`422`) add a `details` list naming
each invalid field, without repeating the submitted value.

Request bodies must be JSON (`Content-Type: application/json`); others get
`415`.

## Logging and request IDs

Every response carries an `X-Request-ID` header. A client may send its own
`X-Request-ID` (8 to 64 letters, digits, `-` or `_`); anything else is
replaced with a new random ID. The same ID appears in error bodies and on
every log line for that request, so a reported error can be traced.

Logs go to standard output: readable text in development, one JSON object
per line in production. Each request produces one summary line with the
method, path, status and duration. Query strings, request bodies, headers,
cookies and IP addresses are never logged by the app.

The Flask development server prints its own access lines as well, which do
include the query string and client IP. It is for local use only.

## Users and administrators

There is no public sign-up. The first platform administrator is created from
the terminal (run from `backend/` with the virtual environment active):

    flask --app app create-platform-admin

It asks for an email address, a name and a password (typed twice, hidden).
The password is never accepted as a command-line option, so it cannot end up
in shell history. Passwords must be 12 to 128 characters and are stored only
as Argon2id hashes.

## Schools and memberships

A platform administrator creates schools with `POST /api/v1/platform/schools`
and a body such as
`{"name": "Greenfield Academy", "code": "greenfield-academy", "county_code": 32}`.

- `code` is a short unique identifier: 3 to 50 lowercase letters or digits,
  optionally joined by single hyphens. It is lowercased automatically.
- `county_code` is the county's number in the First Schedule of the
  Constitution, from 1 (Mombasa) to 47 (Nairobi City). Responses include the
  county's name. The full list is in `app/models/school.py`.
- Schools are deactivated, never deleted.

Being a platform administrator does not give access to any school's data.
Access comes only from a membership: a user's role in a school
(`school_admin`, `principal`, `teacher`, `finance_officer`, `registrar`,
`guardian` or `student`). One person can hold several roles in a school.
Until invitations exist, memberships are added from the terminal:

    flask --app app add-membership --email ada@example.com --school-code greenfield-academy --role school_admin

### The active school

Each session works in one school at a time. A user with exactly one school
starts in it at login; otherwise they choose with
`POST /api/v1/auth/active-school` and `{"school_id": "..."}`. The server
checks for an active membership in an active school first, and gives the
same `403` for a school that does not exist, is inactive or is someone
else's. The check is repeated on every request, so deactivating a membership
or a school removes access immediately.

### Roles and permissions

Each role grants an explicit list of permissions, defined in
`app/auth/permissions.py`; nothing is granted by default. A user's
permissions are those of all their active roles in the active school, and
`GET /api/v1/auth/me` lists them as `permissions` (for the interface only:
every endpoint checks on the server).

| Permission       | Roles                       | Allows |
|------------------|-----------------------------|--------|
| `members.read`    | `school_admin`, `principal`              | Listing the school's members |
| `members.manage`  | `school_admin`                           | Deactivating a member |
| `students.read`   | `school_admin`, `principal`, `registrar` | Listing and viewing students |
| `students.manage` | `school_admin`, `registrar`              | Adding, changing and deactivating students |

Teachers have no student access yet: once classes exist they will see only
the students they teach.

A school always keeps at least one active `school_admin`: deactivating the
last one is refused with `409`.

### Audit trail

Security-relevant actions are recorded in the `audit_events` table: who did
what, in which school, to what, whether it succeeded or was refused, and the
request ID. Events hold IDs only. The API's database user can add and read
events but cannot change or delete them. Recorded actions:

| Action                   | When |
|--------------------------|------|
| `school.created`         | A platform admin creates a school |
| `membership.added`       | `flask add-membership` adds or reactivates a role (no actor: terminal) |
| `membership.deactivated` | A member is deactivated, or a deactivation is refused (`404`) |
| `school.selected`        | A user switches school, or is refused (`403`) |
| `platform.access`        | A non-admin is refused a platform endpoint |
| `student.created`        | A student is added |
| `student.updated`        | A student is changed, or a change is refused (`404`) |
| `student.deactivated`    | A student is deactivated, or a deactivation is refused (`404`) |
| A permission name        | A user is refused for lacking that permission, for example `members.manage` |

To read the trail during development:

    sudo -u postgres psql -d sms_dev -c "SELECT occurred_at, action, outcome, target_type FROM audit_events ORDER BY occurred_at"

### Students

A student record holds an admission number (unique within the school, 1 to
30 characters), a full name and an optional date of birth (`YYYY-MM-DD`, not
in the future, at most 30 years ago). Students are deactivated, never
deleted. Only the minimum is stored; further details will arrive with the
features that need them.

- `GET /api/v1/school/students` takes `page` (default 1), `per_page` (1 to
  100, default 50) and `q`, which matches part of the name or admission
  number regardless of letter case. Results are sorted by name.
- `PATCH` changes only the fields sent; `"date_of_birth": null` clears it.
- The school is never taken from the request: a body containing `school_id`
  is refused.

### Database-level isolation (Row-Level Security)

The `students` table is protected by a PostgreSQL Row-Level Security policy:
the API's database user (`sms_app`) can only see or write rows of the school
set for the current transaction. The app sets it from the session's active
school (`app/school_context.py`); with no active school, the database
returns no rows. The setting ends with each transaction, so a reused
connection never carries another school's context. The schema owner
(`sms_migrator`) is not limited, so tests and migrations use it for set-up
and clean-up.

## Login sessions

`POST /api/v1/auth/login` takes `{"email": "...", "password": "..."}`. On
success the server creates a session and sends its random token in an
`HttpOnly`, `SameSite=Lax` cookie (`sms_session` in development,
`__Host-sms_session` with `Secure` in production). The database stores only a
SHA-256 hash of the token.

- A session ends after 30 minutes without activity, or 8 hours after login,
  whichever comes first. Logging out ends it immediately.
- Every failed login gets the same `401` "Invalid email or password.", so the
  response does not reveal which emails have accounts.
- After 10 failed logins for one account, or 50 from one IP address, within
  15 minutes, further attempts get `429` with a `Retry-After` header until
  the old failures leave the window. Accounts are never locked permanently.
- Requests that change data (`POST`, `PUT`, `PATCH`, `DELETE`) are refused
  with `403` if the browser says they come from any site other than
  `FRONTEND_ORIGIN`.

An expired session is deleted when its cookie is next used. To delete all
expired sessions and failed-login records older than 15 minutes (to be
scheduled with deployment):

    flask --app app prune-sessions

## Dependencies

- `requirements.txt`: runtime packages, pinned to exact versions. Production
  installs only this file.
- `requirements-dev.txt`: runtime packages plus test and lint tools.
