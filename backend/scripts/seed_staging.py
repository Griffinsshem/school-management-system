"""Add clearly fake demo data to the STAGING database (run once).

Run from the backend/ folder with the virtual environment active, loading
the staging settings in a subshell so they never touch your terminal session:

    ( set -a; . ./.env.staging; set +a; python scripts/seed_staging.py )

It refuses to run against any database not named sms_staging. You choose one
password (at a hidden prompt) for all the demo accounts; it is never shown or
stored anywhere except as a hash. Every name and email is invented: emails use
example.com, and every student's surname is "Demo".
"""

import getpass
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.auth.passwords import PasswordPolicyError, hash_password  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Membership, School, Student, User  # noqa: E402
from app.school_context import set_database_school  # noqa: E402

STAGING_DATABASE = "sms_staging"

SCHOOLS = {
    "staging-demo-a": ("Staging Demo School A", 47),
    "staging-demo-b": ("Staging Demo School B", 1),
}
# (email, full name, platform administrator?, [(school code, role), ...])
PEOPLE = [
    ("staging.platform@example.com", "Platform Demo", True, []),
    (
        "staging.admin@example.com",
        "Admin Demo",
        False,
        [("staging-demo-a", "school_admin"), ("staging-demo-b", "teacher")],
    ),
    ("staging.principal@example.com", "Principal Demo", False, [("staging-demo-a", "principal")]),
    ("staging.teacher@example.com", "Teacher Demo", False, [("staging-demo-a", "teacher")]),
]
FIRST_NAMES = [
    "Amani",
    "Baraka",
    "Chebet",
    "Daudi",
    "Eshe",
    "Faraji",
    "Gakii",
    "Hamisi",
    "Imani",
    "Jabari",
    "Kamau",
    "Lulu",
]
# Students per school: School A gets all twelve names, School B the first three.
STUDENTS_PER_SCHOOL = {"staging-demo-a": 12, "staging-demo-b": 3}


class SeedError(Exception):
    """A problem the person running the script can fix."""


def check_target(database_url: str | None) -> None:
    """Only ever write demo data into the staging database."""
    name = make_url(database_url).database if database_url else None
    if name != STAGING_DATABASE:
        raise SeedError(
            f"Refusing to add demo data to database '{name}'. "
            f"This script only runs against '{STAGING_DATABASE}'."
        )


def seed(password: str) -> dict[str, int]:
    """Create the demo schools, people and students. Needs an app context."""
    existing = db.session.scalars(select(School.code).where(School.code.in_(SCHOOLS))).all()
    if existing:
        raise SeedError("The demo data is already there (found school " + existing[0] + ").")

    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as error:
        raise SeedError(str(error)) from None

    schools = {
        code: School(code=code, name=name, county_code=county)
        for code, (name, county) in SCHOOLS.items()
    }
    db.session.add_all(schools.values())
    db.session.flush()

    memberships = 0
    for email, full_name, is_platform_admin, roles in PEOPLE:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            is_platform_admin=is_platform_admin,
        )
        db.session.add(user)
        db.session.flush()
        for code, role in roles:
            db.session.add(Membership(user_id=user.id, school_id=schools[code].id, role=role))
            memberships += 1

    students = 0
    for code, count in STUDENTS_PER_SCHOOL.items():
        # Row-Level Security: students can only be added for the current school.
        set_database_school(schools[code].id)
        prefix = code.rsplit("-", 1)[-1].upper()
        for number, first_name in enumerate(FIRST_NAMES[:count], start=1):
            db.session.add(
                Student(
                    school_id=schools[code].id,
                    admission_number=f"DEMO-{prefix}-{number:03d}",
                    full_name=f"{first_name} Demo",
                    # Every other student has a (made-up) date of birth.
                    date_of_birth=date(2014 + number % 4, number, 1) if number % 2 else None,
                )
            )
            students += 1
        db.session.flush()

    db.session.commit()
    return {
        "schools": len(schools),
        "people": len(PEOPLE),
        "memberships": memberships,
        "students": students,
    }


def main() -> None:
    try:
        app = create_app()
        check_target(app.config["SQLALCHEMY_DATABASE_URI"])
        password = getpass.getpass("Password for all demo accounts (hidden): ")
        if getpass.getpass("Type it again: ") != password:
            raise SeedError("The two passwords did not match.")
        with app.app_context():
            counts = seed(password)
    except (SeedError, RuntimeError) as error:
        sys.exit(f"Stopped: {error}")

    print(
        "Added {schools} schools, {people} people, {memberships} roles and "
        "{students} students.".format(**counts)
    )
    print("Demo accounts (all use the password you just chose):")
    for email, _, is_platform_admin, roles in PEOPLE:
        what = ", ".join(f"{role} at {code}" for code, role in roles)
        print(f"  {email:32} {'platform administrator' if is_platform_admin else what}")


if __name__ == "__main__":
    main()
