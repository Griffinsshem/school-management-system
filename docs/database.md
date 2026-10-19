# Database

The backend uses PostgreSQL 16. Schema changes are made only through
migrations (Flask-Migrate / Alembic), never by editing tables by hand.

## Users and databases

| User           | Purpose                     | Can do                                  |
|----------------|-----------------------------|-----------------------------------------|
| `sms_migrator` | Runs migrations             | Owns the schema: create and alter tables |
| `sms_app`      | Used by the running API     | Read, insert, update and delete rows only |

| Database   | Purpose                                                  |
|------------|----------------------------------------------------------|
| `sms_dev`  | Local development                                        |
| `sms_test` | Automated tests. Tests refuse any database not named `*_test`. |

Neither user is a superuser or can create databases or roles. Only these two
users can connect to these databases; other users on the server are refused.

Keeping the API user separate from the schema owner means a compromised API
cannot drop or alter tables. It also keeps PostgreSQL Row-Level Security
available for school isolation later, because table owners bypass it.

## Local setup

Run from the `backend/` folder with the virtual environment active. Your
`.env` must already exist (see the backend README).

**1. Create the users and databases** (once):

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 < scripts/create_local_database.sql
```

**2. Generate passwords**, store them in `.env` and set them in PostgreSQL:

```bash
python scripts/set_local_db_passwords.py | sudo -u postgres psql -v ON_ERROR_STOP=1
```

The script writes `DATABASE_URL`, `MIGRATION_DATABASE_URL`,
`TEST_DATABASE_URL` and `TEST_MIGRATION_DATABASE_URL`. PostgreSQL receives
only salted SCRAM-SHA-256 hashes, and no password is displayed. Run it again
at any time to rotate both passwords.

**3. Apply migrations** to the development database:

```bash
flask --app app db upgrade
```

The test database is migrated automatically by the test suite.

## Working with migrations

```bash
flask --app app db current          # show the applied revision
flask --app app db upgrade          # apply all pending migrations
flask --app app db downgrade        # undo the most recent migration
flask --app app db migrate -m "..." # generate a migration from model changes
```

Migrations always connect with `MIGRATION_DATABASE_URL` (`sms_migrator`); the
API never does. Review every generated migration before applying it.

Tables created by `sms_migrator` automatically grant `sms_app` row access
(`SELECT`, `INSERT`, `UPDATE`, `DELETE`) through default privileges set in
`scripts/create_local_database.sql`.

## Health checks

| Endpoint                    | Checks                    | Responses                            |
|-----------------------------|---------------------------|--------------------------------------|
| `GET /api/v1/health`        | The API process is running | `200 {"status":"ok"}`               |
| `GET /api/v1/health/ready`  | The API can reach the database | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |

Neither response includes hostnames, users, database names or error details.
