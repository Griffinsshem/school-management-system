"""A throwaway API for the browser tests in frontend/e2e.

Playwright starts this automatically (`npx playwright test` in frontend/).
It is not for development use. It:

1. uses ONLY the test database (TEST_DATABASE_URL, whose name must end in
   `_test`; the app refuses anything else),
2. brings that database to the latest migration and EMPTIES every table,
3. adds clearly fake data: an administrator in two schools, a principal and
   a teacher; and a third school with its own administrator and teacher, for
   the attendance tests, which need a school year around today,
4. serves the API on 127.0.0.1:5001, accepting requests only from the
   frontend that Playwright starts on 127.0.0.1:3100 (which adds the shared
   proxy secret below, as on the real hosts).

The backend tests (pytest) also use the test database and empty it before
they start, so do not run both at the same time.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from flask_migrate import upgrade
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Membership, School, User  # noqa: E402

HOST = "127.0.0.1"
PORT = 5001
FRONTEND_ORIGIN = "http://127.0.0.1:3100"
# A fake secret for the browser tests only. Keep in sync with
# frontend/playwright.config.ts.
PROXY_SECRET = "e2e-only-proxy-secret-never-used-anywhere-else"  # noqa: S105
TEST_ENV_KEYS = ("TEST_DATABASE_URL", "TEST_MIGRATION_DATABASE_URL")

# Fake accounts that exist only in the test database. Keep in sync with
# frontend/e2e/helpers.ts.
ADMIN_EMAIL = "e2e.admin@example.com"
PRINCIPAL_EMAIL = "e2e.principal@example.com"
TEACHER_EMAIL = "e2e.teacher@example.com"
# School C, for the attendance tests only.
ATTENDANCE_ADMIN_EMAIL = "e2e.attendance.admin@example.com"
ATTENDANCE_TEACHER_EMAIL = "e2e.attendance.teacher@example.com"
PASSWORD = "e2e only password"  # noqa: S105


def load_test_settings() -> None:
    """Read only the TEST_* connection strings from backend/.env, as pytest does."""
    env_file = BACKEND_DIR / ".env"
    values = dotenv_values(env_file) if env_file.exists() else {}
    for key in TEST_ENV_KEYS:
        if key not in os.environ and values.get(key):
            os.environ[key] = values[key]


def reset_and_seed(app) -> None:
    with app.app_context():
        upgrade()
        # The schema owner empties the tables: the API's own database user
        # cannot (audit events are append-only for it).
        owner = create_engine(app.config["MIGRATION_DATABASE_URI"])
        tables = ", ".join(table.name for table in db.metadata.sorted_tables)
        with owner.begin() as connection:
            connection.execute(text(f"TRUNCATE {tables}"))  # noqa: S608 (names from our models)
        owner.dispose()

        password_hash = hash_password(PASSWORD)
        admin = User(email=ADMIN_EMAIL, full_name="E2E Admin", password_hash=password_hash)
        principal = User(
            email=PRINCIPAL_EMAIL, full_name="E2E Principal", password_hash=password_hash
        )
        teacher = User(email=TEACHER_EMAIL, full_name="E2E Teacher", password_hash=password_hash)
        school_a = School(code="e2e-school-a", name="E2E School A", county_code=47)
        school_b = School(code="e2e-school-b", name="E2E School B", county_code=1)
        attendance_admin = User(
            email=ATTENDANCE_ADMIN_EMAIL,
            full_name="E2E Attendance Admin",
            password_hash=password_hash,
        )
        attendance_teacher = User(
            email=ATTENDANCE_TEACHER_EMAIL,
            full_name="E2E Attendance Teacher",
            password_hash=password_hash,
        )
        school_c = School(code="e2e-school-c", name="E2E School C", county_code=30)
        db.session.add_all(
            [admin, principal, teacher, school_a, school_b]
            + [attendance_admin, attendance_teacher, school_c]
        )
        db.session.flush()
        db.session.add_all(
            [
                Membership(user_id=admin.id, school_id=school_a.id, role="school_admin"),
                Membership(user_id=admin.id, school_id=school_b.id, role="teacher"),
                Membership(user_id=principal.id, school_id=school_a.id, role="principal"),
                Membership(user_id=teacher.id, school_id=school_a.id, role="teacher"),
                Membership(user_id=attendance_admin.id, school_id=school_c.id, role="school_admin"),
                Membership(user_id=attendance_teacher.id, school_id=school_c.id, role="teacher"),
            ]
        )
        db.session.commit()


def main() -> None:
    load_test_settings()
    app = create_app(
        "testing",
        overrides={"FRONTEND_ORIGIN": FRONTEND_ORIGIN, "PROXY_SHARED_SECRET": PROXY_SECRET},
    )
    reset_and_seed(app)
    print(f"E2E API ready on http://{HOST}:{PORT} (test database, fake data)", flush=True)
    # One line per request is noise in the test output; problems still show.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host=HOST, port=PORT, use_reloader=False)


if __name__ == "__main__":
    main()
