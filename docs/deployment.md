# Deployment

**Status:** a STAGING environment only, holding clearly fake data. There is
no production environment yet, and staging must never hold real school or
student data. The gaps to close before real schools use the system are
listed at the end.

## How the parts fit together

```text
browser --https--> Vercel (Next.js, functions in Frankfurt)
                     |  /api/... is forwarded (rewrite in next.config.ts)
                     v
                   Render, Frankfurt:
                     Cloudflare -> load balancer -> proxy in the container
                     -> gunicorn + Flask (2 workers)
                     |  TLS, as sms_app
                     v
                   Neon, Frankfurt: Neon proxy -> PostgreSQL 16
```

The browser only ever talks to the Vercel site, so the login cookie stays
first-party. Render's address is public too, although nothing needs to call
it directly (see "Known gaps").

| Part | Service and plan | Name | Address |
|------|------------------|------|---------|
| Frontend | Vercel, Hobby | `school-management-system` | https://school-management-system-one-peach.vercel.app |
| API | Render web service, Free | `sms-api-staging` (Blueprint `sms-staging`) | https://sms-api-staging-n2f2.onrender.com |
| Database | Neon, Free | project `sms-staging`, database `sms_staging` | (private) |

Addresses are not secrets. Connection strings and passwords are, and they
live only in the hosts' settings and in `backend/.env.staging` on the
operator's computer (never in Git or chat).

## Free-tier limits (checked 2026-10-23)

- **Render Free** sleeps after 15 minutes without requests; the next request
  waits about a minute while it starts. 512 MB of memory; 750 instance hours
  a month. Render's free PostgreSQL expires after 30 days, which is why the
  database is on Neon instead.
- **Neon Free** does not expire, but has storage and compute limits, and its
  compute also sleeps when idle (a short delay on the first query).
- **Vercel Hobby** is for non-commercial use only. Serving paying schools
  needs Vercel Pro or another host.

## Database (Neon)

### Users

The API connects as `sms_app` (rows only) and migrations run as
`sms_migrator` (schema owner), exactly as in development
([database.md](database.md)).

Both are created **with SQL, never with Neon's console, CLI or API**: Neon
makes roles created those ways members of `neon_superuser`, which can bypass
Row-Level Security (the database rule that keeps schools apart). Roles
created with SQL get no such membership. Neon requires plain-text passwords
of at least 60 bits of entropy in SQL; the script uses 256-bit random ones.

One-time set-up, from `backend/` with the virtual environment active:

```bash
python scripts/staging_database.py create
```

It asks for Neon's owner connection string at a hidden prompt (the
**direct** one, not "pooled"; the owner string is not stored), creates both
users and the `sms_staging` database, and writes `backend/.env.staging`
(readable only by you, ignored by Git). Then it checks the result.

### Migrations

Migrations run from the operator's computer, never from Render: Render has
no schema-owner password, so the running API can change rows but never
tables.

```bash
( set -a; . ./.env.staging; set +a
  FLASK_SKIP_DOTENV=1 flask --app app db upgrade )
python scripts/staging_database.py check
```

The parentheses keep the staging settings out of your terminal session.
`FLASK_SKIP_DOTENV=1` stops Flask from also loading the development `.env`,
which would otherwise silently fill in any missing staging value.

`check` connects as `sms_app` and must show only `ok` lines: an encrypted
connection; not a superuser; cannot bypass Row-Level Security; member of no
other role; cannot create tables; every table owned by `sms_migrator`;
Row-Level Security on for students and invitations; audit events cannot be
changed or deleted. Run it after every migration.

Neon's proxy ends TLS before the database, so the database's own
`pg_stat_ssl` view reports no TLS. The check therefore asks this computer's
side of the connection, the part that crosses the internet; the connection
strings also demand `sslmode=require&channel_binding=require`.

Run migrations **before** pushing code that needs them. Render deploys a
commit a few minutes after its checks pass, and Vercel deploys at once.

### Demo data

```bash
( set -a; . ./.env.staging; set +a; python scripts/seed_staging.py )
```

Adds two demo schools, four `@example.com` people (a platform administrator,
a school administrator who is also a teacher in the second school, a
principal and a teacher) and 15 students whose surname is "Demo". It refuses
any database not named `sms_staging`, runs once, and asks for one password
for all demo accounts at a hidden prompt. Use a password used nowhere else:
staging is public.

## API (Render)

`render.yaml` (a Render Blueprint) defines the service: free plan, Frankfurt,
`rootDir: backend`, `pip install -r requirements.txt && pip check`, health
check `/api/v1/health`, and `autoDeployTrigger: checksPass` (a commit is
deployed only after GitHub Actions passes). Python 3.12 comes from
`backend/.python-version`.

| Variable | Value | Where it is set |
|----------|-------|-----------------|
| `APP_ENV` | `production` | `render.yaml` |
| `LOG_LEVEL` | `INFO` | `render.yaml` |
| `WEB_CONCURRENCY` | `2` (Render's default for a free instance is 1) | `render.yaml` |
| `SECRET_KEY` | random, generated by Render | `render.yaml` (`generateValue`) |
| `DATABASE_URL` | `sms_app`'s connection string from `.env.staging` | Render dashboard |
| `FRONTEND_ORIGIN` | the Vercel address above | Render dashboard |
| `TRUSTED_PROXY_COUNT` | `0` (see "Known gaps") | `render.yaml` |

`MIGRATION_DATABASE_URL` is deliberately absent.

### Render turns on gunicorn's access log

Render sets `GUNICORN_CMD_ARGS="--preload --access-logfile - ..."` for every
Python service, and those settings override `gunicorn.conf.py`. The access
log records each request's full address, including the query string (a
student search carries part of a child's name). Two safeguards:

- the start command is `env -u GUNICORN_CMD_ARGS gunicorn -c gunicorn.conf.py
  wsgi:app`, which removes Render's variable;
- `gunicorn.conf.py` refuses to start if the access log is on, whatever turned
  it on, so a mistake fails the deploy instead of leaking quietly.

Measured on 2026-10-24: a request to `/api/v1/health?q=B10-log-check` left
no trace of `B10-log-check` in Render's logs, and only the app's own JSON
lines (path, status, duration) appear.

## Frontend (Vercel)

Project settings: root directory `frontend`, Node.js **22.x** (as in CI),
function region **Frankfurt (fra1)**, and one environment variable,
`API_ORIGIN` = the Render address (no trailing slash). The `/api` forwarding
rule is fixed when the site is built, so **redeploy after changing
`API_ORIGIN`**.

Only the production address matches `FRONTEND_ORIGIN`. Vercel's per-commit
and per-branch preview addresses load, but logging in from them is refused
with `403` (the API only accepts changes from its own frontend). That is
expected.

## Checking a deployment

From your computer:

```bash
API=https://sms-api-staging-n2f2.onrender.com
curl -sS -w ' HTTP %{http_code}\n' "$API/api/v1/health"         # process up
curl -sS -w ' HTTP %{http_code}\n' "$API/api/v1/health/ready"   # database reachable
```

Then the browser smoke checks (read-only; see the
[frontend README](../frontend/README.md#smoke-checks-against-staging)):

```bash
cd frontend
read -rsp "Demo password: " STAGING_PASSWORD; echo; export STAGING_PASSWORD
STAGING_URL=https://school-management-system-one-peach.vercel.app npx playwright test -c playwright.staging.config.ts
unset STAGING_PASSWORD
```

They also confirm the production cookie: `__Host-sms_session` with
`Secure`, `HttpOnly`, `SameSite=Lax` and `Path=/`.

Checked by hand on 2026-10-25 through the Vercel address: after logout the
old cookie is refused (`401`), so sessions really end on the server; a
logout sent with another site's `Origin` is refused (`403`); and pages carry
`Strict-Transport-Security` (added by Vercel), `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy` and
`Permissions-Policy`.

## Changing secrets

- **`SECRET_KEY`:** in Render, Environment, replace the value with a new
  random one (for example from
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`) and
  deploy. Everyone is logged out, and failed-login counters reset.
- **Database passwords:** there is no rotation command yet. As Neon's owner
  (Neon's SQL editor), run `ALTER ROLE sms_app PASSWORD '...'` with a new
  random password of at least 60 bits, then update `DATABASE_URL` in both
  `backend/.env.staging` and Render. The same applies to `sms_migrator`
  (only `.env.staging` uses it).
- **Neon's owner password:** reset it in Neon's console after set-up if it
  was ever copied anywhere it should not be. The app never uses it.

## Client IP addresses (measured 2026-10-24)

Login rate limiting counts failures per IP address, so the API must see each
visitor's real address, and nothing a visitor can forge. A temporary
diagnostic endpoint (`/api/v1/diagnostics/client-ip`, off unless
`CLIENT_IP_DIAGNOSTICS=1`) showed:

| Route | Direct caller seen by gunicorn | `X-Forwarded-For` arriving |
|-------|-------------------------------|----------------------------|
| Through Vercel | `127.0.0.1` (Render's proxy in the container) | `visitor, Vercel, Cloudflare, Render` |
| Through Vercel, with a forged header | `127.0.0.1` | the same: Vercel discards the forged value |
| Directly to Render | `127.0.0.1` | `visitor, Cloudflare, Render` |
| Directly to Render, with a forged header | `127.0.0.1` | `forged, visitor, Cloudflare, Render` |

So with `TRUSTED_PROXY_COUNT=0` every visitor shares one address, and no
single setting is right for both routes: `3` finds the visitor when Render is
called directly but only Vercel's address through Vercel; `4` finds the
visitor through Vercel but accepts a forged address when Render is called
directly. The fix (feature B11) is to let only Vercel call the API, then use
`4` and measure again.

## Known gaps before real schools

- **Client IP and direct access to Render** (above). Until fixed, one person
  making 50 failed logins in 15 minutes blocks logins for everyone for 15
  minutes. Per-account limits work regardless.
- **`flask prune-sessions` is not scheduled.** Expired sessions are deleted
  when next used, and old failed-login records are only meaningless hashes,
  but a scheduler is needed.
- **Vercel's own request logs** have not been checked for query strings.
- **Backups and restore** have not been tested; Neon's free plan keeps only a
  short history.
- **No monitoring or alerts**, no Content Security Policy yet (see
  [security-notes.md](security-notes.md)), and Vercel Hobby's
  non-commercial terms.
