# Deployment

**Status:** a STAGING environment only, holding clearly fake data. There is
no production environment yet, and staging must never hold real school or
student data. The gaps to close before real schools use the system are
listed at the end.

## How the parts fit together

```text
browser --https--> Vercel (Next.js, functions in Frankfurt)
                     |  /api/... is forwarded by src/proxy.ts, adding the shared
                     |  secret and the visitor's address
                     v
                   Render, Frankfurt:
                     Cloudflare -> load balancer -> proxy in the container
                     -> gunicorn + Flask (2 workers)
                     |  TLS, as sms_app
                     v
                   Neon, Frankfurt: Neon proxy -> PostgreSQL 16
```

The browser only ever talks to the Vercel site, so the login cookie stays
first-party. Render's address is public too, but the API refuses every
request that lacks the secret only the frontend adds (health checks
excepted), so it cannot be used directly (see "Client IP addresses").

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

If `.env.staging` is lost (for example with a computer) or a password may
have leaked, give both users new passwords and write a new file:

```bash
python scripts/staging_database.py rotate
```

It asks for the owner connection string the same way, then runs the checks.
Replace `DATABASE_URL` on Render straight away: the API cannot open new
database connections with its old password.

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
Row-Level Security on for students, invitations, academic years, terms, classes, class teachers, enrolments, attendance, guardians and subjects; audit events cannot be
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
| `PROXY_SHARED_SECRET` | the secret shared with Vercel (same value) | Render dashboard |
| `TRUSTED_PROXY_COUNT` | `0`: the visitor's address comes from the frontend instead | `render.yaml` |

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
function region **Frankfurt (fra1)**, and two environment variables:

- `API_ORIGIN` = the Render address (no trailing slash);
- `PROXY_SHARED_SECRET` = the same value as on Render, for **Production
  only**, marked **Sensitive** (Vercel never shows it again).

Vercel applies changed settings to the next deployment, so **redeploy after
changing either**.

Only the production deployment has the secret, so Vercel's per-commit and
per-branch preview addresses load but their API requests are refused with
`403`. That is expected.

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
- **Database passwords:** `python scripts/staging_database.py rotate` (see
  "Users"), then replace `DATABASE_URL` on Render.
- **`PROXY_SHARED_SECRET`:** generate a new value
  (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), set it
  on Render and on Vercel (Production), and redeploy both. Only one value is
  accepted at a time, so API requests are refused with `403` for the few
  minutes between the two deploys; fine for staging, to be revisited for
  production.
- **Neon's owner password:** reset it in Neon's console after set-up if it
  was ever copied anywhere it should not be. The app never uses it.

## Client IP addresses

Login rate limiting counts failures per IP address, so the API must see each
visitor's real address, and nothing a visitor can forge. A temporary
diagnostic endpoint (removed again in B11) measured what reaches the API.

### Before B11 (measured 2026-10-24)

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
directly.

### Since B11 (measured 2026-10-26)

The frontend (`src/proxy.ts`) adds two headers to every `/api` request it
forwards: `X-SMS-Proxy-Secret` (the shared secret) and `X-SMS-Client-IP`
(the visitor's address, taken from the `X-Forwarded-For` that Vercel
replaces). Copies sent by a visitor are removed first. The API refuses
requests without the right secret and trusts `X-SMS-Client-IP` only with it.

| Route | Result |
|-------|--------|
| Through Vercel | the rate limiter sees the visitor's own address |
| Through Vercel, forged `X-Forwarded-For` or `X-SMS-Client-IP` | the same: the forgeries are ignored |
| Directly to Render, with or without forged headers | `403` |
| Health checks directly to Render | `200` |

`TRUSTED_PROXY_COUNT` stays `0`. The visitor's address is only taken from
`X-Forwarded-For` on Vercel (or where `TRUST_X_FORWARDED_FOR=1` is set): a
self-hosted Next.js server would pass on whatever the visitor sent.

## Known gaps before real schools

- **One shared proxy secret at a time:** changing it means a few minutes of
  refused API requests (see "Changing secrets").
- **`flask prune-sessions` is not scheduled.** Expired sessions are deleted
  when next used, and old failed-login records are only meaningless hashes,
  but a scheduler is needed.
- **Vercel's own request logs** have not been checked for query strings.
- **Backups and restore** have not been tested; Neon's free plan keeps only a
  short history.
- **No monitoring or alerts**, no Content Security Policy yet (see
  [security-notes.md](security-notes.md)), and Vercel Hobby's
  non-commercial terms.
