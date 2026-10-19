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
| `DATABASE_URL`                | API connection as `sms_app` (rows only).                        |
| `MIGRATION_DATABASE_URL`      | Migration connection as `sms_migrator` (schema owner).          |
| `TEST_DATABASE_URL`           | Test connection as `sms_app` to `sms_test`.                     |
| `TEST_MIGRATION_DATABASE_URL` | Test migration connection as `sms_migrator` to `sms_test`.      |

The app refuses to start if `SECRET_KEY` or `DATABASE_URL` is missing, so a
misconfigured server fails loudly instead of running with unsafe settings.

## Endpoints

| Method | Path                   | Response                                          |
|--------|------------------------|---------------------------------------------------|
| GET    | `/api/v1/health`       | `200 {"status":"ok"}`                             |
| GET    | `/api/v1/health/ready` | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |

Errors are always JSON in the form
`{"error": {"code": "...", "message": "..."}}` and never include stack traces.

## Dependencies

- `requirements.txt`: runtime packages, pinned to exact versions. Production
  installs only this file.
- `requirements-dev.txt`: runtime packages plus test and lint tools.
