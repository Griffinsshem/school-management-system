from sqlalchemy import func, select

from app.auth.passwords import verify_password
from app.extensions import db
from app.models import User

PASSWORD = "correct horse battery"


def _run(app, email="Admin@Example.com", name="Ada Admin", password_input=None):
    if password_input is None:
        password_input = f"{PASSWORD}\n{PASSWORD}\n"
    runner = app.test_cli_runner()
    return runner.invoke(
        args=["create-platform-admin", "--email", email, "--name", name],
        input=password_input,
    )


def _user_count(app) -> int:
    with app.app_context():
        return db.session.scalar(select(func.count()).select_from(User))


def test_creates_a_platform_admin(db_app):
    result = _run(db_app)

    assert result.exit_code == 0, result.output
    assert "Platform administrator created: admin@example.com" in result.output
    with db_app.app_context():
        user = db.session.scalar(select(User).where(User.email == "admin@example.com"))
        assert user.is_platform_admin is True
        assert user.full_name == "Ada Admin"
        assert verify_password(user.password_hash, PASSWORD)


def test_password_and_hash_never_appear_in_the_output(db_app):
    result = _run(db_app)

    assert PASSWORD not in result.output
    assert "argon2" not in result.output


def test_refuses_a_duplicate_email(db_app):
    _run(db_app)
    result = _run(db_app, email="ADMIN@example.com")

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert _user_count(db_app) == 1


def test_refuses_a_weak_password(db_app):
    result = _run(db_app, password_input="short\nshort\n")

    assert result.exit_code != 0
    assert "at least 12 characters" in result.output
    assert _user_count(db_app) == 0


def test_refuses_mismatched_confirmation(db_app):
    # Click re-prompts after a mismatch; with no further input it aborts.
    result = _run(db_app, password_input=f"{PASSWORD}\n{PASSWORD}x\n")

    assert result.exit_code != 0
    assert _user_count(db_app) == 0


def test_refuses_an_invalid_email(db_app):
    result = _run(db_app, email="not-an-email")

    assert result.exit_code != 0
    assert "valid email" in result.output
    assert _user_count(db_app) == 0
